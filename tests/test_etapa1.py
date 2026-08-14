"""
SafeGas Monitor — Teste de Sanidade da Etapa 1
===============================================
Verifica que:
1. A estrutura de pastas está correta
2. Os módulos de configuração importam sem erro
3. Os contratos de dados serializam e desserializam corretamente
"""

import sys
import os
import json
from datetime import datetime, timezone

# Garantir que o diretório raiz está no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_imports():
    """Testa que todos os módulos da Etapa 1 importam sem erro."""
    from config.settings import (
        GAS_CONFIG, SOCKET_HOST, SOCKET_PORT,
        ALERT_CRITICAL_THRESHOLD, MONGO_URI
    )
    assert "CH4" in GAS_CONFIG, "CH4 deve estar em GAS_CONFIG"
    assert GAS_CONFIG["CH4"]["lel_percent"] == 5.0
    assert ALERT_CRITICAL_THRESHOLD == 50.0
    print("  [OK] config/settings.py importado com sucesso")


def test_data_contracts():
    """Testa serialização e desserialização do TelemetryPacket."""
    from config.data_contracts import TelemetryPacket, GasReading
    import uuid

    packet = TelemetryPacket(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
        temperature_c=28.5,
        readings=[
            GasReading(gas_id="CH4",  raw_ppm=1200.0, raw_percent=0.12),
            GasReading(gas_id="CO",   raw_ppm=250.0,  raw_percent=0.025),
            GasReading(gas_id="H2S",  raw_ppm=50.0,   raw_percent=0.005),
        ]
    )

    # Serializar → desserializar → verificar integridade
    json_str = packet.to_json()
    assert isinstance(json_str, str), "to_json deve retornar string"

    recovered = TelemetryPacket.from_json(json_str)
    assert recovered.device_id == "EPI-001"
    assert recovered.temperature_c == 28.5
    assert len(recovered.readings) == 3
    assert recovered.readings[0].gas_id == "CH4"
    assert recovered.readings[0].raw_percent == 0.12

    print(f"  [OK] TelemetryPacket serializado ({len(json_str)} bytes) e desserializado com sucesso")
    print(f"       Conteúdo: device={recovered.device_id}, "
          f"temp={recovered.temperature_c}°C, "
          f"gases={[r.gas_id for r in recovered.readings]}")


def test_project_structure():
    """Verifica a existência dos arquivos e pastas esperados."""
    root = os.path.join(os.path.dirname(__file__), "..")
    expected = [
        "main.py",
        "requirements.txt",
        "config/settings.py",
        "config/data_contracts.py",
        "epi_simulator/simulator.py",
        "epi_simulator/client.py",
        "central_command/server.py",
        "central_command/filters/digital_filters.py",
        "central_command/lel/lel_calculator.py",
        "database/repositories.py",
        "reports/report_generator.py",
    ]
    for path in expected:
        full = os.path.normpath(os.path.join(root, path))
        assert os.path.exists(full), f"Arquivo ausente: {path}"
    print(f"  [OK] Todos os {len(expected)} arquivos de estrutura presentes")


def run_all():
    print("\n" + "=" * 55)
    print("  SafeGas Monitor — Testes de Sanidade da Etapa 1")
    print("=" * 55)
    tests = [test_imports, test_data_contracts, test_project_structure]
    passed = 0
    for t in tests:
        try:
            print(f"\n[TESTE] {t.__name__}")
            t()
            passed += 1
        except Exception as e:
            print(f"  [FALHOU] {e}")
    print(f"\n{'=' * 55}")
    print(f"  Resultado: {passed}/{len(tests)} testes passaram")
    print("=" * 55 + "\n")
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
