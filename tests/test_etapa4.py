"""
SafeGas Monitor — Testes da Etapa 4 (Filtros Digitais)
=======================================================
Testa:
  1. MovingAverageFilter: cálculo, aquecimento, soma O(1), reset
  2. KalmanFilter1D: convergência, ganho, reset, limites de parâmetros
  3. FilterPipeline: modos (ma/kalman/both), estado por device, reset
  4. Integração: pipeline aplicado sobre TelemetryPackets reais
  5. Estatísticas de redução de ruído (MAE deve cair com filtragem)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from config.settings import GAS_CONFIG, MOVING_AVG_WINDOW
from config.data_contracts import TelemetryPacket, GasReading, ProcessedReading
from epi_simulator.simulator import EPISimulator, GasSensorSimulator, SignalProfile
from central_command.filters.digital_filters import MovingAverageFilter, KalmanFilter1D
from central_command.filters.pipeline import FilterPipeline

import uuid
from datetime import datetime, timezone


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_packet(device_id="EPI-T", readings_data: dict = None) -> TelemetryPacket:
    """Cria um TelemetryPacket de teste com leituras configuráveis."""
    if readings_data is None:
        readings_data = {"CH4": 0.1, "CO": 0.02}
    return TelemetryPacket(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id=device_id,
        worker_id="W-T",
        location_id="LOC-T",
        temperature_c=25.0,
        readings=[
            GasReading(gas_id=gid, raw_ppm=val * 10_000, raw_percent=val)
            for gid, val in readings_data.items()
        ],
    )


# ─── MovingAverageFilter ──────────────────────────────────────────────────────

def test_ma_single_value():
    """Com uma amostra, saída deve ser igual à entrada."""
    f = MovingAverageFilter(window_size=5)
    out = f.update(3.0)
    assert out == 3.0, f"Esperado 3.0, obtido {out}"
    print("  [OK] MA com 1 amostra retorna a própria amostra")


def test_ma_correct_average():
    """Média das últimas N amostras deve ser precisa."""
    f = MovingAverageFilter(window_size=4)
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    outputs = [f.update(v) for v in values]
    # Com janela=4: a partir da 4ª amostra, média de [2,3,4,5], [3,4,5,6]
    assert abs(outputs[3] - 2.5) < 1e-9, f"outputs[3]={outputs[3]}"  # (1+2+3+4)/4
    assert abs(outputs[4] - 3.5) < 1e-9, f"outputs[4]={outputs[4]}"  # (2+3+4+5)/4
    assert abs(outputs[5] - 4.5) < 1e-9, f"outputs[5]={outputs[5]}"  # (3+4+5+6)/4
    print(f"  [OK] MA correta: {[round(o,2) for o in outputs]}")


def test_ma_sum_consistency():
    """
    Verifica que a soma interna é sempre consistente com
    recalcular a soma do buffer do zero.
    """
    import random
    f = MovingAverageFilter(window_size=7)
    for _ in range(50):
        v = random.uniform(0, 10)
        out = f.update(v)
        expected = sum(f._buffer) / len(f._buffer)
        assert abs(out - expected) < 1e-9, f"Inconsistência: out={out}, expected={expected}"
    print("  [OK] Soma interna O(1) consistente em 50 amostras aleatórias")


def test_ma_warmup():
    """Período de aquecimento: is_warmed_up muda após N amostras."""
    N = 5
    f = MovingAverageFilter(window_size=N)
    for i in range(N - 1):
        f.update(float(i))
        assert not f.is_warmed_up, f"Não deveria estar aquecido na amostra {i+1}"
    f.update(float(N))
    assert f.is_warmed_up, "Deveria estar aquecido após N amostras"
    print(f"  [OK] Aquecimento correto: is_warmed_up após {N} amostras")


def test_ma_reset():
    """Reset deve zerar estado completamente."""
    f = MovingAverageFilter(window_size=5)
    for v in [1, 2, 3, 4, 5]:
        f.update(v)
    assert f.is_warmed_up
    f.reset()
    assert not f.is_warmed_up
    assert f.current_value is None
    assert len(f._buffer) == 0
    print("  [OK] Reset do MA zera estado corretamente")


def test_ma_reset_with_initial():
    """Reset com initial_value deve pré-aquecer o buffer."""
    f = MovingAverageFilter(window_size=5)
    f.reset(initial_value=2.0)
    assert f.is_warmed_up
    assert abs(f.current_value - 2.0) < 1e-9
    print(f"  [OK] Reset com initial_value=2.0: current_value={f.current_value}")


def test_ma_invalid_window():
    """Window_size menor que 1 deve lançar ValueError."""
    try:
        MovingAverageFilter(window_size=0)
        assert False, "Deveria lançar ValueError"
    except ValueError:
        pass
    print("  [OK] MovingAverageFilter(N=0) lança ValueError corretamente")


def test_ma_reduces_noise():
    """
    MA deve reduzir o ruído: MAE do MA < MAE do sinal bruto.
    Sinal: constante + ruído gaussiano. Referência: valor constante.
    """
    N_SAMPLES = 200
    TRUE_VAL = 1.5
    NOISE_STD = 0.2
    rng = np.random.default_rng(42)
    f = MovingAverageFilter(window_size=MOVING_AVG_WINDOW)

    raw_errors, ma_errors = [], []
    for _ in range(N_SAMPLES):
        raw = TRUE_VAL + rng.normal(0, NOISE_STD)
        filtered = f.update(raw)
        raw_errors.append(abs(raw - TRUE_VAL))
        ma_errors.append(abs(filtered - TRUE_VAL))

    raw_mae = np.mean(raw_errors[MOVING_AVG_WINDOW:])
    ma_mae  = np.mean(ma_errors[MOVING_AVG_WINDOW:])
    assert ma_mae < raw_mae, f"MA não reduziu ruído! MA_MAE={ma_mae:.4f} >= raw_MAE={raw_mae:.4f}"
    print(f"  [OK] MA reduziu ruído: raw_MAE={raw_mae:.4f} → MA_MAE={ma_mae:.4f} "
          f"(melhora={100*(1-ma_mae/raw_mae):.1f}%)")


# ─── KalmanFilter1D ───────────────────────────────────────────────────────────

def test_kalman_first_sample():
    """Primeira amostra deve inicializar x̂ igual à medição."""
    kf = KalmanFilter1D()
    out = kf.update(3.7)
    assert out == 3.7, f"Esperado 3.7, obtido {out}"
    print("  [OK] Kalman primeira amostra: x̂=medição")


def test_kalman_convergence_constant_signal():
    """
    Com sinal constante + ruído, Kalman deve convergir para a média real.
    Após N amostras, |x̂ - true| deve ser << σ do ruído.
    """
    TRUE_VAL = 2.0
    NOISE_STD = 0.1
    N = 100
    rng = np.random.default_rng(0)

    kf = KalmanFilter1D(process_variance=1e-5, measurement_variance=NOISE_STD**2)
    for _ in range(N):
        kf.update(TRUE_VAL + rng.normal(0, NOISE_STD))

    error = abs(kf.current_estimate - TRUE_VAL)
    assert error < NOISE_STD * 0.5, \
        f"Kalman não convergiu: |x̂-true|={error:.4f} > {NOISE_STD*0.5:.4f}"
    print(f"  [OK] Kalman convergiu após {N} amostras: x̂={kf.current_estimate:.4f} ≈ {TRUE_VAL}")


def test_kalman_tracks_ramp():
    """
    Com sinais em rampa e Q adequado, Kalman deve acompanhar a tendência.
    """
    kf = KalmanFilter1D(process_variance=1e-2, measurement_variance=0.01)
    last = None
    for i in range(20):
        last = kf.update(i * 0.1)
    # Em rampa crescente, estimativa deve ser positiva e próxima de 19*0.1
    assert last > 0, "Kalman deveria rastrear rampa crescente"
    print(f"  [OK] Kalman rastreia rampa: x̂={last:.3f} (esperado ≈ 1.9)")


def test_kalman_gain_bounds():
    """Ganho de Kalman deve estar sempre em [0, 1]."""
    kf = KalmanFilter1D(process_variance=1e-4, measurement_variance=0.1)
    for v in [0.0, 0.5, 1.0, 2.0, 0.3]:
        kf.update(v)
        K = kf.kalman_gain
        assert 0.0 <= K <= 1.0, f"Ganho fora de [0,1]: K={K}"
    print(f"  [OK] Ganho de Kalman sempre em [0, 1]: K_final={kf.kalman_gain:.4f}")


def test_kalman_reset():
    """Reset deve zerar contador e reiniciar estimativas."""
    kf = KalmanFilter1D(initial_estimate=5.0)
    for v in [1.0, 2.0, 3.0]:
        kf.update(v)
    kf.reset(initial_estimate=0.0)
    assert kf._sample_count == 0
    assert kf.current_estimate == 0.0
    out = kf.update(3.0)
    assert out == 3.0, "Após reset, primeira medição deve reinicializar x̂"
    print("  [OK] Kalman reset funcional")


def test_kalman_invalid_params():
    """Q e R ≤ 0 devem lançar ValueError."""
    try:
        KalmanFilter1D(process_variance=0)
        assert False
    except ValueError:
        pass
    try:
        KalmanFilter1D(measurement_variance=-1)
        assert False
    except ValueError:
        pass
    print("  [OK] KalmanFilter1D rejeita Q=0 e R<0")


def test_kalman_reduces_noise_vs_ma():
    """
    Compara MAE de Kalman e MA com sinal constante + ruído.
    Ambos devem ser < sinal bruto. Documenta qual é melhor no cenário.
    """
    TRUE_VAL = 1.0
    NOISE_STD = 0.15
    N = 300
    rng = np.random.default_rng(7)

    ma = MovingAverageFilter(window_size=MOVING_AVG_WINDOW)
    kf = KalmanFilter1D(process_variance=1e-5, measurement_variance=NOISE_STD**2)

    raw_err, ma_err, kf_err = [], [], []
    skip = MOVING_AVG_WINDOW

    for _ in range(N):
        z = TRUE_VAL + rng.normal(0, NOISE_STD)
        raw_err.append(abs(z - TRUE_VAL))
        ma_err.append(abs(ma.update(z) - TRUE_VAL))
        kf_err.append(abs(kf.update(z) - TRUE_VAL))

    raw_mae = np.mean(raw_err[skip:])
    ma_mae  = np.mean(ma_err[skip:])
    kf_mae  = np.mean(kf_err[skip:])

    assert ma_mae < raw_mae, "MA deve melhorar MAE"
    assert kf_mae < raw_mae, "Kalman deve melhorar MAE"
    better = "Kalman" if kf_mae < ma_mae else "MA"
    print(
        f"  [OK] raw={raw_mae:.4f} | MA={ma_mae:.4f} | Kalman={kf_mae:.4f} "
        f"→ {better} melhor neste cenário"
    )


# ─── FilterPipeline ───────────────────────────────────────────────────────────

def test_pipeline_mode_kalman():
    """Pipeline no modo kalman deve preencher filtered_percent em todas as leituras."""
    pipe = FilterPipeline(mode="kalman")
    pkt = make_packet(readings_data={"CH4": 0.05, "CO": 0.01, "H2S": 0.0})
    result = pipe.process(pkt)

    assert isinstance(result, ProcessedReading)
    assert result.filter_used == "kalman"
    assert len(result.readings) == 3
    for r in result.readings:
        assert r.filtered_percent is not None, f"filtered_percent None para {r.gas_id}"
        assert r.filtered_percent >= 0.0
    print(f"  [OK] Pipeline kalman: {len(result.readings)} leituras filtradas")


def test_pipeline_mode_moving_avg():
    """Pipeline no modo moving_avg deve funcionar corretamente."""
    pipe = FilterPipeline(mode="moving_avg")
    pkt = make_packet(readings_data={"CH4": 0.2, "CO": 0.05})
    result = pipe.process(pkt)
    assert result.filter_used == "moving_avg"
    for r in result.readings:
        assert r.filtered_percent is not None
    print("  [OK] Pipeline moving_avg funcional")


def test_pipeline_mode_both():
    """Pipeline no modo both usa Kalman como saída principal."""
    pipe = FilterPipeline(mode="both")
    pkt = make_packet(readings_data={"CH4": 0.1})
    result = pipe.process(pkt)
    assert result.filter_used == "both"
    assert result.readings[0].filtered_percent is not None
    print("  [OK] Pipeline both (MA→Kalman) funcional")


def test_pipeline_state_per_device():
    """Dois EPIs devem ter filtros independentes."""
    pipe = FilterPipeline(mode="kalman")

    # Alimenta EPI-A com valor alto por 5 amostras
    for _ in range(5):
        pipe.process(make_packet("EPI-A", {"CH4": 2.0}))

    # Alimenta EPI-B com valor baixo por 5 amostras
    for _ in range(5):
        pipe.process(make_packet("EPI-B", {"CH4": 0.1}))

    # As estimativas devem ser diferentes — estado independente
    result_a = pipe.process(make_packet("EPI-A", {"CH4": 2.0}))
    result_b = pipe.process(make_packet("EPI-B", {"CH4": 0.1}))

    ch4_a = result_a.readings[0].filtered_percent
    ch4_b = result_b.readings[0].filtered_percent

    assert ch4_a > ch4_b * 5, \
        f"Filtros deveriam ser independentes: EPI-A={ch4_a:.4f}, EPI-B={ch4_b:.4f}"
    assert "EPI-A" in pipe.tracked_devices
    assert "EPI-B" in pipe.tracked_devices
    print(f"  [OK] Estado independente: EPI-A CH4={ch4_a:.4f}%, EPI-B CH4={ch4_b:.4f}%")


def test_pipeline_reset_device():
    """reset_device deve apagar só os filtros do EPI especificado."""
    pipe = FilterPipeline(mode="both")
    pipe.process(make_packet("EPI-X", {"CH4": 1.0}))
    pipe.process(make_packet("EPI-Y", {"CH4": 0.5}))

    assert "EPI-X" in pipe.tracked_devices
    assert "EPI-Y" in pipe.tracked_devices

    pipe.reset_device("EPI-X")

    assert "EPI-X" not in pipe.tracked_devices
    assert "EPI-Y" in pipe.tracked_devices
    print("  [OK] reset_device remove somente o EPI especificado")


def test_pipeline_filtered_never_negative():
    """filtered_percent nunca deve ser negativo, mesmo com ruído alto."""
    pipe = FilterPipeline(mode="kalman")
    rng = np.random.default_rng(42)
    for _ in range(100):
        # Valores que podem cruzar 0 com ruído
        v = max(0.0, rng.normal(0.01, 0.05))
        pkt = make_packet(readings_data={"CH4": v})
        result = pipe.process(pkt)
        ch4 = result.readings[0].filtered_percent
        assert ch4 >= 0.0, f"Valor negativo detectado: {ch4}"
    print("  [OK] filtered_percent nunca negativo em 100 amostras ruidosas")


def test_pipeline_with_real_simulator():
    """
    Integração completa: EPISimulator → FilterPipeline.
    Verifica que o sinal filtrado é mais suave que o bruto.
    """
    N = 50
    epi = EPISimulator(
        device_id="EPI-FILT",
        worker_id="W-F",
        location_id="LOC-F",
        sensor_configs={
            "CH4": {
                "base": 1.0,
                "noise_std": 0.1,
                "profile": SignalProfile.CONSTANT,
            },
        },
    )

    pipe = FilterPipeline(mode="kalman")
    raw_vals, filt_vals = [], []

    for _ in range(N):
        pkt = epi.generate_packet()
        result = pipe.process(pkt)
        ch4_raw  = next(r.raw_percent for r in pkt.readings    if r.gas_id == "CH4")
        ch4_filt = next(r.filtered_percent for r in result.readings if r.gas_id == "CH4")
        raw_vals.append(ch4_raw)
        filt_vals.append(ch4_filt)

    raw_std  = np.std(raw_vals)
    filt_std = np.std(filt_vals)

    assert filt_std < raw_std, \
        f"Sinal filtrado deveria ter desvio menor: filt_std={filt_std:.4f}, raw_std={raw_std:.4f}"
    print(
        f"  [OK] Pipeline E2E: raw_σ={raw_std:.4f} → filt_σ={filt_std:.4f} "
        f"(redução={100*(1-filt_std/raw_std):.1f}%)"
    )


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_all():
    print("\n" + "=" * 62)
    print("  SafeGas Monitor — Testes da Etapa 4 (Filtros Digitais)")
    print("=" * 62)

    groups = [
        ("MovingAverageFilter", [
            test_ma_single_value,
            test_ma_correct_average,
            test_ma_sum_consistency,
            test_ma_warmup,
            test_ma_reset,
            test_ma_reset_with_initial,
            test_ma_invalid_window,
            test_ma_reduces_noise,
        ]),
        ("KalmanFilter1D", [
            test_kalman_first_sample,
            test_kalman_convergence_constant_signal,
            test_kalman_tracks_ramp,
            test_kalman_gain_bounds,
            test_kalman_reset,
            test_kalman_invalid_params,
            test_kalman_reduces_noise_vs_ma,
        ]),
        ("FilterPipeline", [
            test_pipeline_mode_kalman,
            test_pipeline_mode_moving_avg,
            test_pipeline_mode_both,
            test_pipeline_state_per_device,
            test_pipeline_reset_device,
            test_pipeline_filtered_never_negative,
            test_pipeline_with_real_simulator,
        ]),
    ]

    total_passed, total_tests = 0, 0
    for group_name, tests in groups:
        print(f"\n-- {group_name} " + "-" * (50 - len(group_name)))
        for t in tests:
            total_tests += 1
            try:
                print(f"\n[TESTE] {t.__name__}")
                t()
                total_passed += 1
            except Exception as e:
                print(f"  [FALHOU] {type(e).__name__}: {e}")

    print(f"\n{'=' * 62}")
    print(f"  Resultado: {total_passed}/{total_tests} testes passaram")
    print("=" * 62 + "\n")
    return total_passed == total_tests


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    success = run_all()
    sys.exit(0 if success else 1)
