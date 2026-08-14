"""
SafeGas Monitor — Handler do Pipeline Completo (Etapas 4 – 7)
=============================================================
Encadeia as etapas de processamento recebidas pelo servidor:

    TelemetryPacket (Etapa 3)
        → FilterPipeline.process()       (Etapa 4)
        → LELCalculator.calculate()      (Etapa 5)
        → AlertManager.classify()        (Etapa 5)
        → MongoTelemetryRepository       (Etapa 6)
        → LatexReportGenerator           (Etapa 7 — apenas em CRITICAL)

O `PipelineHandler` é passado como `on_packet` ao `CentralCommandServer`.

Uso em main.py:
    handler = PipelineHandler()
    server = CentralCommandServer(on_packet=handler)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from collections import deque
from typing import Optional

from config.data_contracts import TelemetryPacket, ProcessedReading
from config.settings import REPORT_HISTORY_SIZE
from central_command.filters.pipeline import FilterPipeline, FilterMode
from central_command.lel.lel_calculator import LELCalculator
from central_command.alerts.alert_manager import AlertManager
from central_command.server import ClientSession
from database.nosql.mongo_repository import MongoTelemetryRepository
from reports.latex.report_generator import LatexReportGenerator

# Import opcional para evitar dependência circular se o TUI não for usado
try:
    from ui.tui.state import MonitorState
except ImportError:
    MonitorState = None

log = logging.getLogger(__name__)


class PipelineHandler:
    """
    Orquestrador do pipeline de processamento de telemetria.

    Cria internamente:
      - FilterPipeline   (Etapa 4)
      - LELCalculator    (Etapa 5)
      - AlertManager     (Etapa 5)

    Pode ser usado diretamente como callable:
        handler = PipelineHandler()
        server = CentralCommandServer(on_packet=handler)
    """

    def __init__(
        self,
        filter_mode: FilterMode = "kalman",
        verbose_output: bool = True,
        enable_mongo: bool = True,
        monitor_state: Optional['MonitorState'] = None,
    ):
        """
        Args:
            filter_mode:    modo do filtro ('moving_avg', 'kalman', 'both')
            verbose_output: se True, imprime resumo de cada pacote no terminal
            enable_mongo:   se False, desativa a persistência no MongoDB
            monitor_state:  estado TUI compartilhado (opcional)
        """
        self._filter_pipeline = FilterPipeline(mode=filter_mode)
        self._lel_calculator  = LELCalculator()
        self._alert_manager   = AlertManager()
        self._verbose         = verbose_output
        self._packets_processed = 0
        self._incidents_generated = 0
        self._monitor_state = monitor_state

        # Etapa 6: Repositório MongoDB (modo degradado se indisponível)
        self._mongo = MongoTelemetryRepository() if enable_mongo else None
        if self._mongo and self._mongo.is_available:
            log.info("Persistência MongoDB ativa.")
        else:
            log.info("Persistência MongoDB desativada (modo sem banco).")

        # Etapa 7: Gerador de laudos LaTeX
        self._report_generator = LatexReportGenerator(compile_pdf=True)

        # Histórico por dispositivo (buffer circular, tamanho configurado em settings)
        self._history: dict[str, deque[ProcessedReading]] = {}

        log.info("PipelineHandler inicializado: filtro=%s", filter_mode)

    # ------------------------------------------------------------------
    def __call__(
        self,
        packet: TelemetryPacket,
        session: Optional[ClientSession] = None,
    ) -> ProcessedReading:
        """
        Processa um TelemetryPacket pelo pipeline completo.

        Args:
            packet:  pacote recebido do EPI
            session: sessão do cliente (opcional, para contexto de log)

        Returns:
            ProcessedReading completamente preenchido:
              - filtered_percent    ← Etapa 4 (Filtros)
              - lel_contribution    ← Etapa 5 (Le Chatelier)
              - lel_mix_percent     ← Etapa 5
              - risk_ratio_percent  ← Etapa 5
              - alert_level         ← Etapa 5 (AlertManager)
        """
        self._packets_processed += 1

        # ── Etapa 4: Filtragem ────────────────────────────────────────────────────────
        processed = self._filter_pipeline.process(packet)

        # ── Etapa 5a: Cálculo de LEL ──────────────────────────────────────────
        lel_result = self._lel_calculator.calculate(
            readings=processed.readings,
            temperature_c=packet.temperature_c,
            use_filtered=True,
        )

        # ── Etapa 5b: Classificação de Alerta ──────────────────────────────
        processed = self._alert_manager.classify(processed, lel_result)

        # ── Atualiza histórico por dispositivo ─────────────────────────────────
        dev = processed.device_id
        if dev not in self._history:
            self._history[dev] = deque(maxlen=REPORT_HISTORY_SIZE)
        self._history[dev].append(processed)

        # ── Saída de terminal (modo verbose) ────────────────────────────────
        if self._verbose:
            self._print_summary(packet, processed, lel_result)

        # ── Etapa 6: Persistência no MongoDB ──────────────────────────────
        if self._mongo:
            self._mongo.insert_reading(processed)

        # ── Atualiza o estado da TUI (Etapa 8) ─────────────────────────────
        if self._monitor_state:
            self._monitor_state.update_from_reading(processed, lel_result)

        # ── Etapa 7: Laudo LaTeX se CRITICAL ──────────────────────────────
        if processed.alert_level == "CRITICAL":
            self._generate_report(processed, lel_result)

        return processed

    # ------------------------------------------------------------------
    def _generate_report(self, processed, lel_result):
        """Gera laudo LaTeX e insere IncidentRecord no MongoDB (Etapa 7)."""
        try:
            history = list(self._history.get(processed.device_id, []))
            incident = self._report_generator.generate(processed, lel_result, history)
            self._incidents_generated += 1

            # Persiste incidente no MongoDB (Etapa 6 + 7 integrado)
            if self._mongo and incident:
                self._mongo.insert_incident(incident)

            # Atualiza TUI (Etapa 8)
            if self._monitor_state and incident:
                self._monitor_state.add_incident(
                    incident_id=incident.incident_id,
                    device_id=incident.device_id,
                    worker_id=incident.worker_id,
                    peak_risk_ratio=incident.peak_risk_ratio,
                    triggered_at=incident.triggered_at,
                    latex_path=incident.latex_report_path,
                )

        except Exception as e:
            # Não deixa falha no gerador derrubar o servidor
            log.error("Erro ao gerar laudo LaTeX: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    def _print_summary(self, packet, processed, lel_result):
        """Imprime resumo legível no terminal da Central."""
        ts = packet.timestamp[11:19]
        level = processed.alert_level
        r     = lel_result.risk_ratio_percent

        # Ícone por nível
        icons = {
            "NORMAL":    " ",
            "ATTENTION": "!",
            "WARNING":   "!!",
            "CRITICAL":  "!!CRITICO!!",
        }
        icon = icons.get(level, "?")

        gases = " | ".join(
            f"{rd.gas_id}={rd.filtered_percent*100:.3f}%"
            for rd in processed.readings
            if rd.filtered_percent and rd.filtered_percent > 1e-5
        ) or "todos zerados"

        print(
            f"[CENTRAL] [{ts}] {icon} {packet.device_id} | "
            f"R={r:.1f}% | LEL_mix={lel_result.lel_mix_percent:.3f}% | "
            f"T={packet.temperature_c:.1f}C | {level} | {gases}"
        )

    # ------------------------------------------------------------------
    @property
    def stats(self) -> dict:
        """Estatísticas combinadas do handler."""
        return {
            "packets_processed":   self._packets_processed,
            "incidents_generated": self._incidents_generated,
            "alert_counts":        self._alert_manager.stats,
            "filter_mode":         self._filter_pipeline.mode,
            "tracked_devices":     list(self._filter_pipeline.tracked_devices),
            "mongo_available":     self._mongo.is_available if self._mongo else False,
        }

    def set_critical_callback(self, callback) -> None:
        """Define o callback para eventos CRITICAL (para Etapa 7)."""
        self._alert_manager.on_critical = callback

    def set_warning_callback(self, callback) -> None:
        """Define o callback para eventos WARNING."""
        self._alert_manager.on_warning = callback

    def __repr__(self) -> str:
        return (
            f"PipelineHandler(filtro={self._filter_pipeline.mode}, "
            f"processados={self._packets_processed})"
        )
