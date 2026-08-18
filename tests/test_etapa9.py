"""
SafeGas Monitor — Testes da Etapa 9 (Web Dashboard & API REST)
==============================================================
Testa os endpoints da FastAPI utilizando o TestClient.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from api.server import app, init_api
from ui.tui.state import MonitorState
from datetime import datetime, timezone
import uuid

# Mock classes for MonitorState items
class MockIncident:
    def __init__(self):
        self.incident_id = "INC-TEST-123"
        self.device_id = "EPI-WEB"
        self.peak_risk_ratio = 85.5
        self.latex_path = "incident.tex"
        self.ts_short = "12:00:00"

class MockAlert:
    def __init__(self):
        self.ts_short = "12:00:00"
        self.device_id = "EPI-WEB"
        self.alert_level = "WARNING"
        self.risk_ratio = 65.0
        self.gases = "CH4=10.0%"

class MockDevice:
    def __init__(self):
        self.device_id = "EPI-WEB"
        self.worker_id = "W-WEB"
        self.location_id = "LOC-WEB"
        self.alert_level = "WARNING"
        self.risk_ratio = 65.0
        self.temperature_c = 30.0
        self.last_seen_short = "12:00:00"
        self.packets_received = 100

class MockState:
    def __init__(self):
        self.devices = [MockDevice()]
        self.alert_history = [MockAlert()]
        self.incidents = [MockIncident()]
        self.stats = {
            "uptime_s": 100,
            "total_packets": 200,
            "total_critical": 5,
            "devices_count": 1,
            "incidents_count": 1,
            "throughput_pps": 2.0
        }

def test_api_stats():
    init_api(MockState())
    client = TestClient(app)
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["uptime_s"] == 100
    assert data["devices_count"] == 1
    print("  [OK] GET /api/stats retorna dados corretos")

def test_api_devices():
    init_api(MockState())
    client = TestClient(app)
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_id"] == "EPI-WEB"
    assert data[0]["risk_ratio"] == 65.0
    print("  [OK] GET /api/devices retorna dados corretos")

def test_api_history():
    init_api(MockState())
    client = TestClient(app)
    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["alert_level"] == "WARNING"
    print("  [OK] GET /api/history retorna dados corretos")

def test_api_incidents():
    init_api(MockState())
    client = TestClient(app)
    response = client.get("/api/incidents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["incident_id"] == "INC-TEST"
    assert data[0]["latex_path"] == "incident.tex"
    print("  [OK] GET /api/incidents retorna dados corretos")

def run_all():
    print("\n" + "=" * 65)
    print("  SafeGas Monitor — Testes da Etapa 9 (API REST)")
    print("=" * 65)

    tests = [
        test_api_stats,
        test_api_devices,
        test_api_history,
        test_api_incidents,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  [FALHOU] {t.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("=" * 65)

if __name__ == "__main__":
    run_all()
