"""
SafeGas Monitor — Web API e Dashboard (FastAPI) — Etapa 9
=========================================================
Fornece uma API REST para consultar o estado atual dos EPIs, histórico e incidentes,
e serve a interface web (Dashboard) via arquivos estáticos.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

from ui.tui.state import MonitorState

app = FastAPI(title="SafeGas Monitor API", version="1.0")

# Permitir CORS para desenvolvimento local se necessário
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# O estado será injetado pelo run_central.py
_monitor_state: MonitorState = None

def init_api(state: MonitorState):
    """Inicializa a API associando o estado compartilhado da Central."""
    global _monitor_state
    _monitor_state = state

# ── Endpoints da API ────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    """Retorna estatísticas globais da Central."""
    if not _monitor_state:
        return {}
    return _monitor_state.stats

@app.get("/api/devices")
def get_devices() -> list[Dict[str, Any]]:
    """Retorna a lista de dispositivos ativos e seu status."""
    if not _monitor_state:
        return []
    
    return [
        {
            "device_id": d.device_id,
            "worker_id": d.worker_id,
            "location_id": d.location_id,
            "alert_level": d.alert_level,
            "risk_ratio": d.risk_ratio,
            "temperature_c": d.temperature_c,
            "last_seen": d.last_seen_short,
            "packets": d.packets_received
        }
        for d in _monitor_state.devices
    ]

@app.get("/api/history")
def get_history() -> list[Dict[str, Any]]:
    """Retorna o histórico recente de eventos anormais."""
    if not _monitor_state:
        return []
    
    return [
        {
            "timestamp": e.ts_short,
            "device_id": e.device_id,
            "alert_level": e.alert_level,
            "risk_ratio": e.risk_ratio,
            "gases": e.gases
        }
        for e in _monitor_state.alert_history
    ]

@app.get("/api/incidents")
def get_incidents() -> list[Dict[str, Any]]:
    """Retorna os incidentes críticos (com laudo)."""
    if not _monitor_state:
        return []
    
    return [
        {
            "timestamp": i.ts_short,
            "incident_id": i.incident_id[:8],
            "device_id": i.device_id,
            "peak_risk_ratio": i.peak_risk_ratio,
            "latex_path": i.latex_path
        }
        for i in _monitor_state.incidents
    ]


# ── Arquivos Estáticos ──────────────────────────────────────────────────────
# Monta a pasta 'api/static' para servir o frontend no endpoint '/'
static_path = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
