"""
SafeGas Monitor — Testes da Etapa 2 (Simulador de EPI)
=======================================================
Testa:
  1. GasSensorSimulator: ruído gaussiano, limites físicos, todos os perfis
  2. EPISimulator: geração de pacotes, callback, múltiplos sensores
  3. Integridade dos TelemetryPackets gerados
  4. Serialização/desserialização round-trip dos pacotes gerados
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from config.settings import GAS_CONFIG
from config.data_contracts import TelemetryPacket, GasReading
from epi_simulator.simulator import GasSensorSimulator, EPISimulator, SignalProfile


# ─── Helpers ──────────────────────────────────────────────────────────────────

def collect_readings(sensor: GasSensorSimulator, n: int) -> list[float]:
    """Coleta n leituras de raw_percent de um sensor."""
    return [sensor.next_reading().raw_percent for _ in range(n)]


# ─── Testes do GasSensorSimulator ─────────────────────────────────────────────

def test_sensor_basic_creation():
    """Cria um sensor válido e um inválido."""
    s = GasSensorSimulator("CH4", base_concentration=0.5, noise_std=0.01)
    assert s.gas_id == "CH4"
    assert s.lel == 5.0

    try:
        GasSensorSimulator("GAS_INEXISTENTE")
        assert False, "Deveria lançar ValueError"
    except ValueError:
        pass

    print("  [OK] Criação de sensor: válido e inválido tratado corretamente")


def test_sensor_noise_gaussian():
    """
    Verifica que o ruído é estatisticamente gaussiano.
    Com N=500 amostras, média deve ser ≈ base e desvio ≈ noise_std.
    """
    base, sigma, n = 1.0, 0.1, 500
    sensor = GasSensorSimulator("CH4", base_concentration=base, noise_std=sigma)
    readings = collect_readings(sensor, n)

    mean   = float(np.mean(readings))
    std    = float(np.std(readings))

    # Tolerâncias estatísticas (3σ / √N)
    assert abs(mean - base) < 3 * sigma / np.sqrt(n), \
        f"Média {mean:.4f} desviou muito do esperado {base}"
    assert abs(std - sigma) < 0.05, \
        f"Desvio padrão {std:.4f} longe do esperado {sigma}"

    print(f"  [OK] Ruído gaussiano: μ={mean:.4f} (esp={base}), σ={std:.4f} (esp={sigma})")


def test_sensor_physical_limits():
    """Concentração nunca deve sair de [0, UEL]."""
    sensor = GasSensorSimulator("CH4", base_concentration=0.0, noise_std=2.0)
    readings = collect_readings(sensor, 200)
    assert all(0.0 <= r <= GAS_CONFIG["CH4"]["uel_percent"] for r in readings), \
        "Leitura fora dos limites físicos!"
    print("  [OK] Limites físicos [0, UEL] respeitados em 200 amostras ruidosas")


def test_sensor_profile_ramp_up():
    """Perfil RAMP_UP deve ter tendência crescente."""
    rate = 0.05
    sensor = GasSensorSimulator("CH4", base_concentration=0.0,
                                 noise_std=0.001,  # ruído mínimo
                                 profile=SignalProfile.RAMP_UP,
                                 ramp_rate=rate)
    r1 = sensor.next_reading().raw_percent
    for _ in range(9):
        sensor.next_reading()
    r10 = sensor.next_reading().raw_percent
    assert r10 > r1, f"RAMP_UP: r10={r10:.4f} deveria ser > r1={r1:.4f}"
    print(f"  [OK] Perfil RAMP_UP: r1={r1:.4f}% → r10={r10:.4f}% (crescente)")


def test_sensor_profile_ramp_down():
    """Perfil RAMP_DOWN deve ter tendência decrescente e nunca negativa."""
    sensor = GasSensorSimulator("CH4", base_concentration=1.0,
                                 noise_std=0.001,
                                 profile=SignalProfile.RAMP_DOWN,
                                 ramp_rate=0.05)
    readings = collect_readings(sensor, 30)
    assert all(r >= 0.0 for r in readings), "RAMP_DOWN gerou valor negativo!"
    assert readings[-1] < readings[0], "RAMP_DOWN não decresceu!"
    print(f"  [OK] Perfil RAMP_DOWN: {readings[0]:.4f}% → {readings[-1]:.4f}% (decrescente, ≥ 0)")


def test_sensor_profile_step():
    """Perfil STEP deve mudar de valor exatamente no sample configurado."""
    step_at, target = 5, 2.0
    sensor = GasSensorSimulator("CH4", base_concentration=0.0,
                                 noise_std=0.0001,  # ruído quase zero
                                 profile=SignalProfile.STEP,
                                 step_at_sample=step_at,
                                 step_target=target)
    before = [sensor.next_reading().raw_percent for _ in range(step_at)]
    after  = sensor.next_reading().raw_percent
    assert all(b < 0.01 for b in before), "Antes do degrau deveria ser ≈ 0"
    assert abs(after - target) < 0.01, f"Após degrau: {after:.4f} ≠ {target}"
    print(f"  [OK] Perfil STEP: 0% → {after:.4f}% na amostra {step_at}")


def test_sensor_sinusoidal():
    """Perfil SINUSOIDAL deve produzir valores que oscilam ao redor da base."""
    base, amp = 0.5, 0.1
    sensor = GasSensorSimulator("CH4", base_concentration=base,
                                 noise_std=0.001,
                                 profile=SignalProfile.SINUSOIDAL,
                                 sine_amplitude=amp, sine_period_s=10.0)
    readings = collect_readings(sensor, 100)
    mean_r = np.mean(readings)
    assert abs(mean_r - base) < 0.05, f"Média senoidal {mean_r:.4f} ≠ base {base}"
    assert max(readings) > base, "Senoide não ultrapassou a base"
    assert min(readings) < base, "Senoide não ficou abaixo da base"
    print(f"  [OK] Perfil SINUSOIDAL: μ={mean_r:.4f}, max={max(readings):.4f}, min={min(readings):.4f}")


def test_sensor_reset():
    """Reset deve zerar o contador de amostras."""
    sensor = GasSensorSimulator("CH4", base_concentration=0.0,
                                 profile=SignalProfile.RAMP_UP, ramp_rate=0.1)
    for _ in range(10):
        sensor.next_reading()
    sensor.reset(base_concentration=0.0)
    assert sensor._sample_count == 0
    print("  [OK] Reset do sensor funcional (sample_count zerado)")


# ─── Testes do EPISimulator ───────────────────────────────────────────────────

def test_epi_generates_packet():
    """EPISimulator deve gerar TelemetryPackets válidos."""
    epi = EPISimulator("EPI-TEST", "W-001", "LOC-001")
    packet = epi.generate_packet()

    assert isinstance(packet, TelemetryPacket)
    assert packet.device_id == "EPI-TEST"
    assert packet.worker_id == "W-001"
    assert packet.location_id == "LOC-001"
    assert len(packet.readings) == len(GAS_CONFIG)
    assert packet.temperature_c > 0
    assert packet.protocol_version == "1.0"
    print(f"  [OK] TelemetryPacket gerado: {len(packet.readings)} gases, T={packet.temperature_c}°C")


def test_epi_all_gases_present():
    """Todos os gases de GAS_CONFIG devem estar no pacote."""
    epi = EPISimulator("EPI-TEST", "W-001", "LOC-001")
    packet = epi.generate_packet()
    gas_ids_in_packet = {r.gas_id for r in packet.readings}
    expected = set(GAS_CONFIG.keys())
    assert gas_ids_in_packet == expected, \
        f"Gases ausentes: {expected - gas_ids_in_packet}"
    print(f"  [OK] Todos os gases presentes: {sorted(gas_ids_in_packet)}")


def test_epi_packet_serialization():
    """Pacote gerado deve sobreviver ao round-trip JSON."""
    epi = EPISimulator("EPI-TEST", "W-001", "LOC-001")
    original = epi.generate_packet()
    json_str = original.to_json()
    recovered = TelemetryPacket.from_json(json_str)

    assert recovered.packet_id == original.packet_id
    assert recovered.device_id == original.device_id
    assert recovered.temperature_c == original.temperature_c
    assert len(recovered.readings) == len(original.readings)

    # Verifica integridade de cada leitura
    for r_orig, r_rec in zip(original.readings, recovered.readings):
        assert r_rec.gas_id == r_orig.gas_id
        assert r_rec.raw_ppm == r_orig.raw_ppm
        assert r_rec.raw_percent == r_orig.raw_percent

    print(f"  [OK] Round-trip JSON ok ({len(json_str)} bytes, {len(recovered.readings)} gases)")


def test_epi_run_max_packets():
    """run() com max_packets deve parar exatamente após N pacotes."""
    epi = EPISimulator("EPI-TEST", "W-001", "LOC-001")
    collected = []

    # Sobrescreve SAMPLE_RATE_HZ para rodar sem espera real
    import epi_simulator.simulator as sim_module
    original_rate = sim_module.SAMPLE_RATE_HZ
    sim_module.SAMPLE_RATE_HZ = 1000.0  # 1000 Hz → sem espera perceptível

    epi.run(on_packet=collected.append, max_packets=10)

    sim_module.SAMPLE_RATE_HZ = original_rate

    assert len(collected) == 10, f"Esperados 10 pacotes, recebidos {len(collected)}"
    # Verifica que timestamps são únicos
    timestamps = [p.timestamp for p in collected]
    assert len(set(p.packet_id for p in collected)) == 10, "packet_ids duplicados!"
    print(f"  [OK] run(max_packets=10): {len(collected)} pacotes gerados com IDs únicos")


def test_epi_custom_sensor_config():
    """Configuração customizada de sensores deve ser respeitada."""
    epi = EPISimulator(
        "EPI-TEST", "W-001", "LOC-001",
        sensor_configs={
            "CH4": {
                "base": 2.0,
                "noise_std": 0.0001,
                "profile": SignalProfile.CONSTANT,
            }
        }
    )
    # Com ruído quase zero, CH4 deve ser ≈ 2.0%
    readings = [epi.generate_packet() for _ in range(20)]
    ch4_vals = [
        r.raw_percent
        for pkt in readings
        for r in pkt.readings
        if r.gas_id == "CH4"
    ]
    mean_ch4 = np.mean(ch4_vals)
    assert abs(mean_ch4 - 2.0) < 0.01, \
        f"CH4 customizado: média {mean_ch4:.4f} ≠ 2.0"
    print(f"  [OK] Sensor CH4 customizado: μ={mean_ch4:.4f}% (esp=2.0%)")


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_all():
    print("\n" + "=" * 60)
    print("  SafeGas Monitor — Testes da Etapa 2 (Simulador EPI)")
    print("=" * 60)

    sensor_tests = [
        test_sensor_basic_creation,
        test_sensor_noise_gaussian,
        test_sensor_physical_limits,
        test_sensor_profile_ramp_up,
        test_sensor_profile_ramp_down,
        test_sensor_profile_step,
        test_sensor_sinusoidal,
        test_sensor_reset,
    ]
    epi_tests = [
        test_epi_generates_packet,
        test_epi_all_gases_present,
        test_epi_packet_serialization,
        test_epi_run_max_packets,
        test_epi_custom_sensor_config,
    ]

    all_tests = sensor_tests + epi_tests
    passed = 0

    print("\n── GasSensorSimulator ──────────────────────────────────────")
    for t in sensor_tests:
        try:
            print(f"\n[TESTE] {t.__name__}")
            t()
            passed += 1
        except Exception as e:
            print(f"  [FALHOU] {e}")

    print("\n── EPISimulator ────────────────────────────────────────────")
    for t in epi_tests:
        try:
            print(f"\n[TESTE] {t.__name__}")
            t()
            passed += 1
        except Exception as e:
            print(f"  [FALHOU] {e}")

    print(f"\n{'=' * 60}")
    print(f"  Resultado: {passed}/{len(all_tests)} testes passaram")
    print("=" * 60 + "\n")
    return passed == len(all_tests)


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
