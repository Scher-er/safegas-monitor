"""
SafeGas Monitor — Pipeline de Filtragem — Etapa 4
==================================================
Gerencia instâncias de filtros por (device_id, gas_id) e aplica
a filtragem sobre TelemetryPackets recebidos pelo servidor.

Responsabilidades:
  - Criar e manter filtros separados por EPI e por gás
    (cada combinação tem seu próprio histórico de amostras)
  - Aceitar um TelemetryPacket e retornar um ProcessedReading
    com os campos filtered_percent preenchidos
  - Permitir escolha entre Média Móvel, Kalman ou ambos

Encadeamento no pipeline do servidor (Etapas 4-7):
    TelemetryPacket
        → FilterPipeline.process()       ← ESTA ETAPA
        → LELCalculator.calculate()      ← Etapa 5
        → Repositories.insert()          ← Etapa 6
        → ReportGenerator.generate()     ← Etapa 7 (se CRÍTICO)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
from typing import Dict, Tuple, Literal
from dataclasses import asdict

from config.settings import (
    MOVING_AVG_WINDOW,
    KALMAN_PROCESS_VARIANCE,
    KALMAN_MEASUREMENT_VARIANCE,
    GAS_CONFIG,
)
from config.data_contracts import TelemetryPacket, GasReading, ProcessedReading
from central_command.filters.digital_filters import MovingAverageFilter, KalmanFilter1D

log = logging.getLogger(__name__)

# Chave interna: (device_id, gas_id)
_FilterKey = Tuple[str, str]

# Tipo de filtro ativo
FilterMode = Literal["moving_avg", "kalman", "both"]


class FilterPipeline:
    """
    Gerencia o estado de filtragem de múltiplos EPIs e múltiplos gases.

    Cria lazily uma instância de cada filtro por (device_id, gas_id)
    na primeira leitura — sem necessidade de pré-registro dos EPIs.

    Uso:
        pipeline = FilterPipeline(mode="kalman")
        processed = pipeline.process(packet)
        # processed.readings[i].filtered_percent  ← valor suavizado
    """

    def __init__(
        self,
        mode: FilterMode = "kalman",
        moving_avg_window: int = MOVING_AVG_WINDOW,
        kalman_Q: float = KALMAN_PROCESS_VARIANCE,
        kalman_R: float = KALMAN_MEASUREMENT_VARIANCE,
    ):
        """
        Args:
            mode:              qual filtro usar:
                               'moving_avg' → Média Móvel
                               'kalman'     → Filtro de Kalman
                               'both'       → aplica ambos; usa Kalman como saída principal
            moving_avg_window: N para Média Móvel
            kalman_Q:          variância do ruído de processo
            kalman_R:          variância do ruído de medição
        """
        self.mode = mode
        self._ma_window = moving_avg_window
        self._kalman_Q  = kalman_Q
        self._kalman_R  = kalman_R

        # Dicionários de instâncias de filtro: {(device_id, gas_id): FilterInstance}
        self._ma_filters: Dict[_FilterKey, MovingAverageFilter] = {}
        self._kf_filters: Dict[_FilterKey, KalmanFilter1D]      = {}

        log.info(
            "FilterPipeline criado: mode=%s, MA_N=%d, K_Q=%.2e, K_R=%.2e",
            mode, moving_avg_window, kalman_Q, kalman_R,
        )

    # ------------------------------------------------------------------
    def _get_ma(self, key: _FilterKey) -> MovingAverageFilter:
        """Retorna (criando se necessário) o filtro MA para a chave."""
        if key not in self._ma_filters:
            self._ma_filters[key] = MovingAverageFilter(self._ma_window)
            log.debug("Novo MovingAverageFilter: device=%s, gas=%s", *key)
        return self._ma_filters[key]

    def _get_kf(self, key: _FilterKey) -> KalmanFilter1D:
        """Retorna (criando se necessário) o filtro Kalman para a chave."""
        if key not in self._kf_filters:
            self._kf_filters[key] = KalmanFilter1D(
                process_variance=self._kalman_Q,
                measurement_variance=self._kalman_R,
            )
            log.debug("Novo KalmanFilter1D: device=%s, gas=%s", *key)
        return self._kf_filters[key]

    # ------------------------------------------------------------------
    def process(self, packet: TelemetryPacket) -> ProcessedReading:
        """
        Aplica filtragem em cada leitura do pacote.

        Para cada GasReading:
          - raw_percent      ← original (mantido intacto)
          - filtered_percent ← saída do(s) filtro(s) configurados

        Args:
            packet: TelemetryPacket recebido do EPI

        Returns:
            ProcessedReading com filtered_percent preenchido em cada leitura.
            Os campos lel_mix_percent, risk_ratio_percent e alert_level são
            deixados como placeholder (preenchidos na Etapa 5).
        """
        filtered_readings: list[GasReading] = []

        for reading in packet.readings:
            key = (packet.device_id, reading.gas_id)
            raw = reading.raw_percent

            # Aplica o filtro selecionado
            if self.mode == "moving_avg":
                filtered = self._get_ma(key).update(raw)
                filter_used = "moving_avg"

            elif self.mode == "kalman":
                filtered = self._get_kf(key).update(raw)
                filter_used = "kalman"

            else:  # "both" — aplica MA como pré-processamento, Kalman como saída
                ma_out  = self._get_ma(key).update(raw)
                filtered = self._get_kf(key).update(ma_out)
                filter_used = "both"

            # Garante que o valor filtrado nunca seja negativo (fisicamente impossível)
            filtered = max(0.0, filtered)

            filtered_readings.append(
                GasReading(
                    gas_id=reading.gas_id,
                    raw_ppm=reading.raw_ppm,
                    raw_percent=reading.raw_percent,
                    filtered_percent=round(filtered, 6),
                )
            )

        return ProcessedReading(
            packet_id=packet.packet_id,
            timestamp=packet.timestamp,
            device_id=packet.device_id,
            worker_id=packet.worker_id,
            location_id=packet.location_id,
            temperature_c=packet.temperature_c,
            readings=filtered_readings,
            # Campos da Etapa 5 (calculados pelo LELCalculator):
            lel_mix_percent=-1.0,
            risk_ratio_percent=-1.0,
            alert_level="PENDING",
            filter_used=filter_used,
        )

    # ------------------------------------------------------------------
    def reset_device(self, device_id: str) -> None:
        """Remove todos os filtros de um EPI (ex: ao desconectar)."""
        keys_to_remove = [k for k in self._ma_filters if k[0] == device_id]
        for k in keys_to_remove:
            del self._ma_filters[k]
        keys_to_remove = [k for k in self._kf_filters if k[0] == device_id]
        for k in keys_to_remove:
            del self._kf_filters[k]
        log.info("Filtros do device '%s' removidos.", device_id)

    def reset_all(self) -> None:
        """Remove todos os filtros (reset global)."""
        self._ma_filters.clear()
        self._kf_filters.clear()
        log.info("Todos os filtros resetados.")

    # ------------------------------------------------------------------
    @property
    def active_filter_count(self) -> int:
        """Número total de instâncias de filtro ativas."""
        return len(self._ma_filters) + len(self._kf_filters)

    @property
    def tracked_devices(self) -> set[str]:
        """Conjunto de device_ids com filtros ativos."""
        devices = {k[0] for k in self._ma_filters}
        devices.update(k[0] for k in self._kf_filters)
        return devices

    def __repr__(self) -> str:
        return (
            f"FilterPipeline(mode={self.mode}, "
            f"devices={len(self.tracked_devices)}, "
            f"filtros_ativos={self.active_filter_count})"
        )
