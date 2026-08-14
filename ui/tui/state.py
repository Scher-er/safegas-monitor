"""
SafeGas Monitor — Estado Thread-Safe do Monitor — Etapa 8
=========================================================
Centraliza o estado compartilhado entre o pipeline (threads do servidor)
e a interface TUI (thread de renderização). Todas as operações são
protegidas por Lock para evitar race conditions.

Estado mantido:
  - Tabela de dispositivos: último ProcessedReading por device_id
  - Histórico de alertas: últimos MAX_HISTORY eventos (todos os níveis)
  - Registro de incidentes: laudos LaTeX gerados
  - Estatísticas globais: uptime, ppm processados, throughput
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config.data_contracts import ProcessedReading
from central_command.lel.lel_calculator import LELResult

# Tamanho máximo do histórico de alertas exibido
MAX_HISTORY = 50
# Tamanho máximo do registro de incidentes
MAX_INCIDENTS = 30


# ─── Dataclasses de estado ────────────────────────────────────────────────────

@dataclass
class DeviceStatus:
    """Estado atual de um dispositivo EPI na Central."""
    device_id:       str
    worker_id:       str
    location_id:     str
    alert_level:     str
    risk_ratio:      float
    lel_mix:         float
    temperature_c:   float
    filter_used:     str
    last_seen:       str       # ISO 8601 timestamp
    packets_received: int = 0

    @property
    def last_seen_short(self) -> str:
        """Retorna apenas HH:MM:SS do timestamp."""
        return self.last_seen[11:19] if len(self.last_seen) >= 19 else self.last_seen


@dataclass
class AlertEvent:
    """Um evento de alerta no histórico."""
    timestamp:   str
    device_id:   str
    alert_level: str
    risk_ratio:  float
    lel_mix:     float
    gases:       str    # "CH4=1.23% | CO=0.50%"

    @property
    def ts_short(self) -> str:
        return self.timestamp[11:19] if len(self.timestamp) >= 19 else self.timestamp


@dataclass
class IncidentEntry:
    """Um incidente com laudo gerado."""
    incident_id:      str
    device_id:        str
    worker_id:        str
    peak_risk_ratio:  float
    triggered_at:     str
    latex_path:       str

    @property
    def ts_short(self) -> str:
        return self.triggered_at[11:19] if len(self.triggered_at) >= 19 else self.triggered_at


# ─── Estado principal (thread-safe) ──────────────────────────────────────────

class MonitorState:
    """
    Estado thread-safe do monitor em tempo real.

    Pode ser atualizado por múltiplas threads do servidor
    e lido pela thread de renderização da TUI sem race conditions.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Dispositivos conectados: device_id → DeviceStatus
        self._devices: dict[str, DeviceStatus] = {}

        # Histórico de alertas (todos os níveis)
        self._alert_history: deque[AlertEvent] = deque(maxlen=MAX_HISTORY)

        # Registro de incidentes CRITICAL com laudo gerado
        self._incidents: deque[IncidentEntry] = deque(maxlen=MAX_INCIDENTS)

        # Estatísticas globais
        self._started_at:    datetime = datetime.now(timezone.utc)
        self._total_packets: int = 0
        self._total_critical: int = 0

    # ── Atualizações (chamadas pelas threads do servidor) ─────────────────────

    def update_from_reading(
        self,
        processed: ProcessedReading,
        lel: LELResult,
    ) -> None:
        """
        Atualiza o estado a partir de um ProcessedReading.
        Chamado pelo MonitorCallback após cada pacote processado.
        """
        # Formata gases detectados
        gases_str = " | ".join(
            f"{r.gas_id}={r.filtered_percent * 100:.3f}%"
            for r in processed.readings
            if r.filtered_percent and r.filtered_percent > 1e-5
        ) or "—"

        with self._lock:
            self._total_packets += 1
            if processed.alert_level == "CRITICAL":
                self._total_critical += 1

            # Atualiza tabela de dispositivos
            existing = self._devices.get(processed.device_id)
            self._devices[processed.device_id] = DeviceStatus(
                device_id=processed.device_id,
                worker_id=processed.worker_id,
                location_id=processed.location_id,
                alert_level=processed.alert_level,
                risk_ratio=lel.risk_ratio_percent,
                lel_mix=lel.lel_mix_percent,
                temperature_c=processed.temperature_c,
                filter_used=processed.filter_used,
                last_seen=processed.timestamp,
                packets_received=(existing.packets_received + 1) if existing else 1,
            )

            # Adiciona ao histórico (apenas ATTENTION+)
            if processed.alert_level != "NORMAL":
                self._alert_history.appendleft(AlertEvent(
                    timestamp=processed.timestamp,
                    device_id=processed.device_id,
                    alert_level=processed.alert_level,
                    risk_ratio=lel.risk_ratio_percent,
                    lel_mix=lel.lel_mix_percent,
                    gases=gases_str,
                ))

    def add_incident(
        self,
        incident_id: str,
        device_id: str,
        worker_id: str,
        peak_risk_ratio: float,
        triggered_at: str,
        latex_path: str,
    ) -> None:
        """Registra um novo incidente com laudo gerado."""
        with self._lock:
            self._incidents.appendleft(IncidentEntry(
                incident_id=incident_id,
                device_id=device_id,
                worker_id=worker_id,
                peak_risk_ratio=peak_risk_ratio,
                triggered_at=triggered_at,
                latex_path=os.path.basename(latex_path),
            ))

    # ── Leituras (chamadas pela thread de renderização) ───────────────────────

    @property
    def devices(self) -> list[DeviceStatus]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: d.device_id)

    @property
    def alert_history(self) -> list[AlertEvent]:
        with self._lock:
            return list(self._alert_history)

    @property
    def incidents(self) -> list[IncidentEntry]:
        with self._lock:
            return list(self._incidents)

    @property
    def stats(self) -> dict:
        with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self._started_at).total_seconds()
            return {
                "uptime_s":      elapsed,
                "total_packets": self._total_packets,
                "total_critical": self._total_critical,
                "devices_count": len(self._devices),
                "incidents_count": len(self._incidents),
                "throughput_pps": round(self._total_packets / max(elapsed, 1), 2),
            }

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    def has_any_critical(self) -> bool:
        with self._lock:
            return any(d.alert_level == "CRITICAL" for d in self._devices.values())
