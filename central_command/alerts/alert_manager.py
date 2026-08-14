"""
SafeGas Monitor — Gerenciador de Alertas — Etapa 5
===================================================
Classifica o nível de risco de um ProcessedReading e executa as
ações correspondentes a cada nível de alerta.

Níveis de alerta (% do LEL_mix):
  ┌──────────────┬────────────────┬─────────────────────────────────────┐
  │ Nível        │ Faixa R        │ Ação                                │
  ├──────────────┼────────────────┼─────────────────────────────────────┤
  │ NORMAL       │ R < 10%        │ Monitoramento contínuo              │
  │ ATTENTION    │ 10% ≤ R < 25%  │ Log especial + aviso sonoro (sim.)  │
  │ WARNING      │ 25% ≤ R < 50%  │ Alerta visual + notif. supervisor   │
  │ CRITICAL     │ R ≥ 50%        │ Bombeiros (sim.) + Laudo LaTeX       │
  └──────────────┴────────────────┴─────────────────────────────────────┘
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from config.settings import (
    ALERT_LOW_THRESHOLD,
    ALERT_MEDIUM_THRESHOLD,
    ALERT_CRITICAL_THRESHOLD,
    GAS_CONFIG,
)
from config.data_contracts import ProcessedReading
from central_command.lel.lel_calculator import LELResult

log = logging.getLogger(__name__)

# Constantes de nível
LEVEL_NORMAL    = "NORMAL"
LEVEL_ATTENTION = "ATTENTION"
LEVEL_WARNING   = "WARNING"
LEVEL_CRITICAL  = "CRITICAL"

_LEVEL_ORDER = [LEVEL_NORMAL, LEVEL_ATTENTION, LEVEL_WARNING, LEVEL_CRITICAL]


def risk_to_level(risk_ratio: float) -> str:
    """
    Converte o fator de risco R (% do LEL_mix) no nível de alerta correspondente.

    Args:
        risk_ratio: R em %, calculado por LELCalculator

    Returns:
        Uma das constantes: NORMAL, ATTENTION, WARNING, CRITICAL
    """
    if risk_ratio >= ALERT_CRITICAL_THRESHOLD:
        return LEVEL_CRITICAL
    elif risk_ratio >= ALERT_MEDIUM_THRESHOLD:
        return LEVEL_WARNING
    elif risk_ratio >= ALERT_LOW_THRESHOLD:
        return LEVEL_ATTENTION
    return LEVEL_NORMAL


class AlertManager:
    """
    Classifica o risco e despacha ações para cada nível de alerta.

    Callbacks registráveis:
      on_attention(processed, lel_result)  — R ≥ 10%
      on_warning(processed, lel_result)    — R ≥ 25%
      on_critical(processed, lel_result)   — R ≥ 50%  → dispara laudo

    Uso:
        mgr = AlertManager()
        mgr.on_critical = lambda p, r: generate_report(p)
        processed = mgr.classify(processed_reading, lel_result)
    """

    def __init__(
        self,
        on_attention: Optional[Callable] = None,
        on_warning:   Optional[Callable] = None,
        on_critical:  Optional[Callable] = None,
    ):
        """
        Args:
            on_attention: callback(processed, lel_result) para R ≥ 10%
            on_warning:   callback(processed, lel_result) para R ≥ 25%
            on_critical:  callback(processed, lel_result) para R ≥ 50%
        """
        self.on_attention = on_attention or self._default_attention
        self.on_warning   = on_warning   or self._default_warning
        self.on_critical  = on_critical  or self._default_critical

        # Estatísticas por nível
        self._counts = {
            LEVEL_NORMAL:    0,
            LEVEL_ATTENTION: 0,
            LEVEL_WARNING:   0,
            LEVEL_CRITICAL:  0,
        }
        self._last_alert_level: Optional[str] = None

    # ------------------------------------------------------------------
    def classify(
        self,
        processed: ProcessedReading,
        lel_result: LELResult,
    ) -> ProcessedReading:
        """
        Classifica o risco, atualiza os campos do ProcessedReading
        e executa o callback correspondente ao nível atingido.

        Args:
            processed:  ProcessedReading vindo do FilterPipeline (Etapa 4)
            lel_result: LELResult vindo do LELCalculator

        Returns:
            ProcessedReading com lel_mix_percent, risk_ratio_percent e
            alert_level preenchidos.
        """
        # Preenche campos do ProcessedReading com resultados do LEL
        processed.lel_mix_percent    = lel_result.lel_mix_percent
        processed.risk_ratio_percent = lel_result.risk_ratio_percent

        level = risk_to_level(lel_result.risk_ratio_percent)
        processed.alert_level = level
        self._counts[level] += 1
        self._last_alert_level = level

        # Calcula contribuição individual de cada gás (Le Chatelier)
        # e preenche lel_contribution em cada GasReading
        for reading in processed.readings:
            gas_id = reading.gas_id
            if gas_id in lel_result.corrections_applied and gas_id in GAS_CONFIG:
                lel_t = lel_result.corrections_applied[gas_id]
                conc  = reading.filtered_percent if reading.filtered_percent is not None \
                        else reading.raw_percent
                reading.lel_contribution = round(conc / lel_t, 6) if lel_t > 0 else 0.0
            else:
                reading.lel_contribution = 0.0

        # Despacha para o callback do nível correspondente
        if level == LEVEL_CRITICAL:
            self._dispatch_critical(processed, lel_result)
        elif level == LEVEL_WARNING:
            self._dispatch_warning(processed, lel_result)
        elif level == LEVEL_ATTENTION:
            self._dispatch_attention(processed, lel_result)
        else:
            log.debug(
                "[NORMAL] device=%s R=%.2f%% LEL_mix=%.4f%%",
                processed.device_id, lel_result.risk_ratio_percent,
                lel_result.lel_mix_percent,
            )

        return processed

    # ------------------------------------------------------------------
    def _dispatch_attention(self, processed: ProcessedReading, lel: LELResult):
        log.info(
            "[ATENCAO] device=%s worker=%s R=%.2f%% gases=%s",
            processed.device_id, processed.worker_id,
            lel.risk_ratio_percent, lel.gases_contributing,
        )
        try:
            self.on_attention(processed, lel)
        except Exception as e:
            log.error("Erro no callback on_attention: %s", e)

    def _dispatch_warning(self, processed: ProcessedReading, lel: LELResult):
        log.warning(
            "[ALERTA] device=%s worker=%s R=%.2f%% LEL_mix=%.4f%%",
            processed.device_id, processed.worker_id,
            lel.risk_ratio_percent, lel.lel_mix_percent,
        )
        try:
            self.on_warning(processed, lel)
        except Exception as e:
            log.error("Erro no callback on_warning: %s", e)

    def _dispatch_critical(self, processed: ProcessedReading, lel: LELResult):
        log.critical(
            "[CRITICO!] device=%s worker=%s R=%.2f%% LEL_mix=%.4f%% T=%.1f°C",
            processed.device_id, processed.worker_id,
            lel.risk_ratio_percent, lel.lel_mix_percent, lel.temperature_c,
        )
        try:
            self.on_critical(processed, lel)
        except Exception as e:
            log.error("Erro no callback on_critical: %s", e)

    # ------------------------------------------------------------------
    # Handlers padrão (substituídos nas Etapas seguintes)
    # ------------------------------------------------------------------
    def _default_attention(self, processed: ProcessedReading, lel: LELResult):
        ts = processed.timestamp[11:19]
        print(
            f"  [ATENCAO] [{ts}] {processed.device_id} | "
            f"R={lel.risk_ratio_percent:.1f}% do LEL | "
            f"gases={lel.gases_contributing}"
        )

    def _default_warning(self, processed: ProcessedReading, lel: LELResult):
        ts = processed.timestamp[11:19]
        print(
            f"  !! [ALERTA] [{ts}] {processed.device_id} | "
            f"R={lel.risk_ratio_percent:.1f}% do LEL | "
            f"LEL_mix={lel.lel_mix_percent:.3f}% v/v"
        )

    def _default_critical(self, processed: ProcessedReading, lel: LELResult):
        ts = processed.timestamp[11:19]
        print(
            f"\n  !! CRITICO !! [{ts}] {processed.device_id} | "
            f"worker={processed.worker_id} | "
            f"R={lel.risk_ratio_percent:.1f}% | "
            f"LEL_mix={lel.lel_mix_percent:.3f}%\n"
            f"  >> Notificando Bombeiros (simulado)...\n"
            f"  >> Gerando laudo tecnico LaTeX... (Etapa 7)\n"
        )

    # ------------------------------------------------------------------
    @property
    def stats(self) -> dict:
        """Contagem acumulada de eventos por nível de alerta."""
        return dict(self._counts)

    @property
    def last_level(self) -> Optional[str]:
        """Último nível de alerta classificado."""
        return self._last_alert_level

    def reset_stats(self) -> None:
        """Zera as estatísticas de contagem."""
        for k in self._counts:
            self._counts[k] = 0

    def __repr__(self) -> str:
        return (
            f"AlertManager(last={self._last_alert_level}, "
            f"counts={self._counts})"
        )
