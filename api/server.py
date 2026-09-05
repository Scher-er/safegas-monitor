import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, send_from_directory
from typing import Dict, Any

from ui.tui.state import MonitorState

app = Flask(__name__, static_folder="static")

_monitor_state: MonitorState = None

def init_api(state: MonitorState):
    global _monitor_state
    _monitor_state = state

@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not _monitor_state:
        return jsonify({})
    return jsonify(_monitor_state.stats)

@app.route("/api/devices", methods=["GET"])
def get_devices():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
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
    ])

@app.route("/api/history", methods=["GET"])
def get_history():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
        {
            "timestamp": e.ts_short,
            "device_id": e.device_id,
            "alert_level": e.alert_level,
            "risk_ratio": e.risk_ratio,
            "gases": e.gases
        }
        for e in _monitor_state.alert_history
    ])

@app.route("/api/incidents", methods=["GET"])
def get_incidents():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
        {
            "timestamp": i.ts_short,
            "incident_id": i.incident_id[:8],
            "device_id": i.device_id,
            "peak_risk_ratio": i.peak_risk_ratio,
            "latex_path": i.latex_path
        }
        for i in _monitor_state.incidents
    ])

# Servir frontend estatico no `/`
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)
