"""
Testes da API REST e Web Dashboard (Flask).
Verifica todos os endpoints de telemetria, histórico, incidentes,
configurações de e-mail e controle dinâmico do simulador.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.server import app, init_api
from epi_simulator.client import SimulationManager


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
            "throughput_pps": 2.0,
        }


def test_api_stats():
    init_api(MockState())
    client = app.test_client()
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.get_json()
    assert data["uptime_s"] == 100
    assert data["devices_count"] == 1
    print("  [OK] GET /api/stats retorna estatísticas globais")


def test_api_devices():
    init_api(MockState())
    client = app.test_client()
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["device_id"] == "EPI-WEB"
    assert data[0]["risk_ratio"] == 65.0
    print("  [OK] GET /api/devices retorna lista de EPIs em monitoramento")


def test_api_history():
    init_api(MockState())
    client = app.test_client()
    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["alert_level"] == "WARNING"
    print("  [OK] GET /api/history retorna histórico de alertas")


def test_api_incidents():
    init_api(MockState())
    client = app.test_client()
    response = client.get("/api/incidents")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["incident_id"] == "INC-TEST"
    assert data[0]["latex_path"] == "incident.tex"
    print("  [OK] GET /api/incidents retorna incidentes críticos")


def test_api_simulator_control():
    mgr = SimulationManager(host="127.0.0.1", port=1883)
    init_api(MockState(), sim_manager=mgr)
    client = app.test_client()

    res_start = client.post(
        "/api/simulator/start-device",
        json={"device_id": "EPI-SIM-01", "worker_id": "F-042", "location_id": "LOC-002"},
    )
    assert res_start.status_code == 200
    payload = res_start.get_json()
    assert payload["success"] is True
    assert payload["device_id"] == "EPI-SIM-01"

    res_active = client.get("/api/simulator/active")
    assert res_active.status_code == 200
    active_list = res_active.get_json()
    assert any(d["device_id"] == "EPI-SIM-01" for d in active_list)

    res_stop = client.post("/api/simulator/stop-device", json={"device_id": "EPI-SIM-01"})
    assert res_stop.status_code == 200
    assert res_stop.get_json()["removed"] is True
    print("  [OK] Controle dinâmico do simulador via API (/api/simulator/*)")


def test_api_serve_report():
    from config.settings import REPORTS_OUTPUT_DIR
    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", REPORTS_OUTPUT_DIR))
    os.makedirs(reports_dir, exist_ok=True)
    sample_file = os.path.join(reports_dir, "incident_test_api.tex")
    with open(sample_file, "w", encoding="utf-8") as f:
        f.write("\\documentclass{article}\\begin{document}Laudo Teste\\end{document}")

    try:
        client = app.test_client()
        res = client.get("/api/reports/incident_test_api.tex")
        assert res.status_code == 200
        assert b"Laudo Teste" in res.data

        res_404 = client.get("/api/reports/inexistente_9999.pdf")
        assert res_404.status_code == 404
        print("  [OK] GET /api/reports/<filename> serve o laudo corretamente")
    finally:
        if os.path.exists(sample_file):
            os.remove(sample_file)


def run_all() -> bool:
    print("\n" + "=" * 60)
    print("  SafeGas Monitor - Testes da API REST (Flask)")
    print("=" * 60)

    tests = [
        test_api_stats,
        test_api_devices,
        test_api_history,
        test_api_incidents,
        test_api_simulator_control,
        test_api_serve_report,
    ]
    passed = 0
    for t in tests:
        try:
            print(f"\n[TESTE] {t.__name__}")
            t()
            passed += 1
        except Exception as e:
            print(f"  [FALHOU] {t.__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"  Resultado: {passed}/{len(tests)} testes passaram")
    print("=" * 60 + "\n")
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
