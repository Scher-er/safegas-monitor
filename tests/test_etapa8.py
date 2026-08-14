"""
SafeGas Monitor — Testes da Etapa 8 (Interface TUI)
===================================================
Testa a lógica de gerenciamento de estado (MonitorState) e a construção
de layouts do Rich (TuiBuilder), garantindo a robustez do monitor.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone

from config.data_contracts import ProcessedReading, GasReading
from central_command.lel.lel_calculator import LELResult
from ui.tui.state import MonitorState
from ui.tui.layout import TuiBuilder


def _make_reading(device_id="EPI-01", level="NORMAL", risk=0.0) -> ProcessedReading:
    return ProcessedReading(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id=device_id,
        worker_id="W-01",
        location_id="L-01",
        temperature_c=25.0,
        readings=[
            GasReading(gas_id="CH4", raw_ppm=0, raw_percent=0.0, filtered_percent=risk/20.0, lel_contribution=0.0)
        ],
        lel_mix_percent=100.0,
        risk_ratio_percent=risk,
        alert_level=level,
        filter_used="kalman",
    )

def _make_lel_result(risk=0.0) -> LELResult:
    return LELResult(
        risk_ratio_percent=risk,
        lel_mix_percent=100.0,
        c_mix_percent=0.0,
        temperature_c=25.0,
        gases_contributing=["CH4"],
        corrections_applied=[],
    )

def test_monitor_state_update_device():
    state = MonitorState()
    assert state.device_count() == 0

    reading = _make_reading("EPI-A", "NORMAL", 5.0)
    state.update_from_reading(reading, _make_lel_result(5.0))

    assert state.device_count() == 1
    devices = state.devices
    assert devices[0].device_id == "EPI-A"
    assert devices[0].packets_received == 1

    # Atualiza mesmo device
    reading2 = _make_reading("EPI-A", "ATTENTION", 15.0)
    state.update_from_reading(reading2, _make_lel_result(15.0))
    
    assert state.device_count() == 1
    assert state.devices[0].packets_received == 2
    assert state.devices[0].alert_level == "ATTENTION"
    print("  [OK] MonitorState: update_from_reading mantém 1 registro por device")

def test_monitor_state_history_limits():
    state = MonitorState()
    # Insere NORMAL (não deve ir pro histórico)
    state.update_from_reading(_make_reading("EPI-1", "NORMAL", 1.0), _make_lel_result(1.0))
    assert len(state.alert_history) == 0

    # Insere mais de MAX_HISTORY
    from ui.tui.state import MAX_HISTORY
    for i in range(MAX_HISTORY + 5):
        state.update_from_reading(_make_reading(f"EPI-{i}", "WARNING", 30.0), _make_lel_result(30.0))
    
    assert len(state.alert_history) == MAX_HISTORY
    print("  [OK] MonitorState: histórico respeita limites de tamanho e descarta NORMAL")

def test_monitor_state_incidents():
    state = MonitorState()
    assert len(state.incidents) == 0

    state.add_incident("INC-1", "EPI-1", "W-1", 55.0, datetime.now().isoformat(), "reports/latex/1.tex")
    state.add_incident("INC-2", "EPI-2", "W-2", 60.0, datetime.now().isoformat(), "reports/latex/2.tex")

    assert len(state.incidents) == 2
    assert state.incidents[0].incident_id == "INC-2" # LIFO (appendleft)
    assert state.incidents[0].latex_path == "2.tex"  # path is basename'd
    print("  [OK] MonitorState: add_incident funciona e basename do path")

def test_tui_builder_renders_without_error():
    state = MonitorState()
    state.update_from_reading(_make_reading("EPI-CRIT", "CRITICAL", 60.0), _make_lel_result(60.0))
    state.add_incident("INC-1", "EPI-CRIT", "W-1", 60.0, datetime.now().isoformat(), "1.tex")

    builder = TuiBuilder(state)
    
    layout = builder.build_layout()
    assert layout is not None

    header = builder.build_header()
    assert "Incidentes (Laudos): 1" in str(header.renderable)

    dev_table = builder.build_devices_table()
    assert dev_table.row_count == 1

    hist_table = builder.build_history_table()
    assert hist_table.row_count == 1

    inc_table = builder.build_incidents_table()
    assert inc_table.row_count == 1
    
    print("  [OK] TuiBuilder: renderiza painéis e tabelas com os dados do estado")


def run_all():
    print("\n" + "=" * 65)
    print("  SafeGas Monitor — Testes da Etapa 8 (TUI)")
    print("=" * 65)

    tests = [
        test_monitor_state_update_device,
        test_monitor_state_history_limits,
        test_monitor_state_incidents,
        test_tui_builder_renders_without_error,
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
