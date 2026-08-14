"""
SafeGas Monitor — Contrato de Dados (Data Contracts)
=====================================================
Define as estruturas de dados trafegadas via Socket e armazenadas
no banco. Usar dataclasses garante tipagem e serialização fácil.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional
import json


# ---------------------------------------------------------------------------
# Leitura individual de um sensor de gás
# ---------------------------------------------------------------------------
@dataclass
class GasReading:
    """Representa a leitura de UM gás em um instante."""
    gas_id: str          # ex: "CH4", "CO", "H2S"
    raw_ppm: float       # leitura bruta do sensor (partes por milhão)
    raw_percent: float   # concentração bruta (% v/v no ar)

    # Preenchidos pela Central após filtragem:
    filtered_percent: Optional[float] = None
    lel_contribution: Optional[float] = None  # Ci / LELi para Le Chatelier


# ---------------------------------------------------------------------------
# Pacote de Telemetria — enviado pelo EPI via Socket a cada amostragem
# ---------------------------------------------------------------------------
@dataclass
class TelemetryPacket:
    """
    Pacote JSON enviado pelo EPI para a Central de Comando via Socket TCP.
    
    Formato de transmissão (JSON serializado):
    {
        "packet_id":   "uuid-v4",
        "timestamp":   "2026-08-13T20:00:00Z",   ← ISO 8601 UTC
        "device_id":   "EPI-001",
        "worker_id":   "F-042",
        "location_id": "LOC-003",
        "temperature_c": 28.5,
        "readings": [
            {"gas_id": "CH4",  "raw_ppm": 1200.0, "raw_percent": 0.12},
            {"gas_id": "CO",   "raw_ppm":  250.0, "raw_percent": 0.025},
            ...
        ],
        "protocol_version": "1.0"
    }
    """
    packet_id:        str
    timestamp:        str               # ISO 8601 UTC
    device_id:        str               # identificador do EPI físico/simulado
    worker_id:        str               # matrícula do funcionário
    location_id:      str               # identificador do local de risco
    temperature_c:    float             # temperatura ambiente (°C)
    readings:         list[GasReading]  # lista de leituras por gás
    protocol_version: str = "1.0"

    def to_json(self) -> str:
        """Serializa o pacote para string JSON (transmissão via Socket)."""
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> "TelemetryPacket":
        """Desserializa um pacote recebido via Socket."""
        d = json.loads(raw)
        readings = [GasReading(**r) for r in d.pop("readings")]
        return TelemetryPacket(readings=readings, **d)


# ---------------------------------------------------------------------------
# Resultado do processamento pela Central de Comando
# ---------------------------------------------------------------------------
@dataclass
class ProcessedReading:
    """
    Resultado gerado pela Central após filtragem + cálculo de risco.
    Armazenado no MongoDB (telemetry collection).
    """
    packet_id:          str
    timestamp:          str
    device_id:          str
    worker_id:          str
    location_id:        str
    temperature_c:      float
    readings:           list[GasReading]    # agora com campos filtrados preenchidos
    lel_mix_percent:    float               # LEL_mix calculado (% v/v)
    risk_ratio_percent: float               # (C_mix / LEL_mix) * 100 %
    alert_level:        str                 # "NORMAL" | "ATTENTION" | "WARNING" | "CRITICAL"
    filter_used:        str                 # "moving_avg" | "kalman"


# ---------------------------------------------------------------------------
# Registro de Incidente (MongoDB — incidents collection)
# ---------------------------------------------------------------------------
@dataclass
class IncidentRecord:
    """
    Criado quando alert_level == CRITICAL.
    Referencia o laudo LaTeX gerado automaticamente.
    """
    incident_id:     str
    triggered_at:    str       # ISO 8601 UTC
    device_id:       str
    worker_id:       str
    location_id:     str
    peak_risk_ratio: float     # maior % do LEL_mix no incidente
    latex_report_path: str     # caminho do .tex gerado
    resolved_at:     Optional[str] = None
