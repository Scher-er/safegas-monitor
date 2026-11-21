"""
Testes de Integração da Camada de Mensageria MQTT e SimulationManager.
Verifica:
  1. Serialização e desserialização JSON de TelemetryPacket para tópicos MQTT
  2. Roteamento de mensagens no CentralCommandServer (_on_message) e rastreamento de sessões
  3. Resiliência contra pacotes malformados (JSON inválido ou incompleto)
  4. Gerenciamento dinâmico de múltiplos EPIs no SimulationManager (add/remove/list)
  5. Integração SimulationManager -> CentralCommandServer -> PipelineHandler
"""

import sys
import os
import uuid
import queue
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.data_contracts import TelemetryPacket, GasReading
from epi_simulator.simulator import EPISimulator
from epi_simulator.client import EPISocketClient, SimulationManager
from central_command.server import CentralCommandServer, ClientSession
from central_command.pipeline_handler import PipelineHandler


class _MockMQTTMessage:
    """Simula uma mensagem MQTT entregue pelo callback do Paho-MQTT."""
    def __init__(self, topic: str, payload_bytes: bytes):
        self.topic = topic
        self.payload = payload_bytes


def make_test_packet(device_id: str = "EPI-TEST") -> TelemetryPacket:
    return TelemetryPacket(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id=device_id,
        worker_id="F-042",
        location_id="LOC-003",
        temperature_c=26.4,
        readings=[
            GasReading(gas_id="CH4", raw_ppm=800.0, raw_percent=0.08),
            GasReading(gas_id="CO", raw_ppm=120.0, raw_percent=0.012),
        ],
    )


def test_packet_json_roundtrip():
    """Garante que o payload trafegado via MQTT preserva todos os campos."""
    pkt = make_test_packet("EPI-MQTT-01")
    raw_json = pkt.to_json()
    recovered = TelemetryPacket.from_json(raw_json)

    assert recovered.packet_id == pkt.packet_id
    assert recovered.device_id == "EPI-MQTT-01"
    assert recovered.worker_id == "F-042"
    assert len(recovered.readings) == 2
    assert recovered.readings[0].gas_id == "CH4"
    assert recovered.readings[0].raw_percent == 0.08
    print("  [OK] Serialização JSON round-trip para publicação MQTT")


def test_central_server_on_message_dispatch():
    """Verifica se o CentralCommandServer processa mensagens MQTT e mantém sessões por EPI."""
    received = []

    def on_packet(packet: TelemetryPacket, session: ClientSession):
        received.append((packet, session))

    server = CentralCommandServer(host="127.0.0.1", port=1883, on_packet=on_packet)
    pkt1 = make_test_packet("EPI-001")
    pkt2 = make_test_packet("EPI-002")

    msg1 = _MockMQTTMessage("safegas/telemetry/EPI-001", pkt1.to_json().encode("utf-8"))
    msg2 = _MockMQTTMessage("safegas/telemetry/EPI-002", pkt2.to_json().encode("utf-8"))
    msg3 = _MockMQTTMessage("safegas/telemetry/EPI-001", pkt1.to_json().encode("utf-8"))

    server._on_message(None, None, msg1)
    server._on_message(None, None, msg2)
    server._on_message(None, None, msg3)

    assert len(received) == 3
    assert server.active_clients == 2
    assert server._sessions["EPI-001"].packets_received == 2
    assert server._sessions["EPI-002"].packets_received == 1
    print("  [OK] CentralCommandServer roteia pacotes MQTT e contabiliza sessões")


def test_central_server_malformed_payload_resilience():
    """Pacotes MQTT corrompidos devem ser descartados sem interromper o servidor."""
    received = []
    server = CentralCommandServer(on_packet=lambda p, s: received.append(p))

    bad_msg1 = _MockMQTTMessage("safegas/telemetry/EPI-ERR", b"{invalid_json")
    bad_msg2 = _MockMQTTMessage("safegas/telemetry/EPI-ERR", b'{"missing_fields": true}')
    valid_pkt = make_test_packet("EPI-OK")
    good_msg = _MockMQTTMessage("safegas/telemetry/EPI-OK", valid_pkt.to_json().encode("utf-8"))

    server._on_message(None, None, bad_msg1)
    server._on_message(None, None, bad_msg2)
    server._on_message(None, None, good_msg)

    assert len(received) == 1
    assert received[0].device_id == "EPI-OK"
    print("  [OK] Resiliência contra payloads MQTT malformados")


def test_simulation_manager_device_lifecycle():
    """Verifica adição, listagem e remoção dinâmica de dispositivos no SimulationManager."""
    mgr = SimulationManager(host="127.0.0.1", port=1883)

    sim1 = mgr.add_device("EPI-101", worker_id="F-042", location_id="LOC-003", scenario="leak")
    sim2 = mgr.add_device("EPI-102", worker_id="F-043", location_id="LOC-002", scenario="baseline")

    active = mgr.list_active()
    ids = {a["device_id"] for a in active}
    assert "EPI-101" in ids and "EPI-102" in ids
    assert sim1.scenario == "leak"
    assert sim2.scenario == "baseline"

    pkt = sim1.generate_packet()
    assert pkt.device_id == "EPI-101"
    assert len(pkt.readings) == 5

    removed = mgr.remove_device("EPI-101")
    assert removed is True
    assert len(mgr.list_active()) == 1
    print("  [OK] Ciclo de vida multi-dispositivo no SimulationManager")


def test_end_to_end_simulator_to_pipeline():
    """Simula fluxo completo: EPISimulator -> Mensagem MQTT -> CentralCommandServer -> PipelineHandler."""
    handler = PipelineHandler(filter_mode="kalman", verbose_output=False, enable_mongo=False)
    server = CentralCommandServer(on_packet=handler)
    epi = EPISimulator.create_scenario("baseline", "EPI-E2E", "F-042", "LOC-002", seed=42)

    for _ in range(5):
        pkt = epi.generate_packet()
        msg = _MockMQTTMessage(f"safegas/telemetry/{pkt.device_id}", pkt.to_json().encode("utf-8"))
        server._on_message(None, None, msg)

    assert handler._packets_processed == 5
    assert server._sessions["EPI-E2E"].packets_received == 5
    print("  [OK] Fluxo integrado E2E: Simulador -> MQTT -> Central -> Pipeline Kalman")


def run_all() -> bool:
    print("\n" + "=" * 60)
    print("  SafeGas Monitor - Testes de Mensageria MQTT e Simulação")
    print("=" * 60)

    tests = [
        test_packet_json_roundtrip,
        test_central_server_on_message_dispatch,
        test_central_server_malformed_payload_resilience,
        test_simulation_manager_device_lifecycle,
        test_end_to_end_simulator_to_pipeline,
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
