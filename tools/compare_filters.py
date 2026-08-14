"""
SafeGas Monitor — Comparação Visual de Filtros (Etapa 4)
=========================================================
Gera um gráfico de 3 painéis comparando:
  - Sinal bruto (com ruído gaussiano)
  - Filtro de Média Móvel (MA)
  - Filtro de Kalman (KF)

Cenário simulado: Vazamento crescente de CH4 (RAMP_UP) com ruído.

Uso:
    python tools/compare_filters.py

Saída:
    docs/filter_comparison.png   ← gráfico salvo
    Terminal: métricas de erro (MAE, RMSE) de cada filtro
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")   # backend sem janela (salva em arquivo)
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from epi_simulator.simulator import GasSensorSimulator, SignalProfile
from central_command.filters.digital_filters import MovingAverageFilter, KalmanFilter1D
from config.settings import MOVING_AVG_WINDOW, KALMAN_PROCESS_VARIANCE, KALMAN_MEASUREMENT_VARIANCE

# ─── Parâmetros do experimento ────────────────────────────────────────────────
N_SAMPLES    = 120          # 2 minutos @ 1 Hz
NOISE_STD    = 0.08         # ruído gaussiano (% v/v) — relativamente alto para visualização
BASE_CONC    = 0.0          # concentração inicial (% v/v)
RAMP_RATE    = 0.03         # crescimento por amostra (% v/v)
MA_WINDOW    = MOVING_AVG_WINDOW        # 10 amostras
KF_Q         = KALMAN_PROCESS_VARIANCE  # 1e-4
KF_R         = KALMAN_MEASUREMENT_VARIANCE  # 0.1
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "..", "docs", "filter_comparison.png")


def run():
    # ─── Gera sinal simulado ──────────────────────────────────────────
    sensor = GasSensorSimulator(
        gas_id="CH4",
        base_concentration=BASE_CONC,
        noise_std=NOISE_STD,
        profile=SignalProfile.RAMP_UP,
        ramp_rate=RAMP_RATE,
    )

    ma = MovingAverageFilter(window_size=MA_WINDOW)
    kf = KalmanFilter1D(
        process_variance=KF_Q,
        measurement_variance=KF_R,
        initial_estimate=BASE_CONC,
    )

    t_axis  = list(range(N_SAMPLES))
    raw_sig = []
    ma_sig  = []
    kf_sig  = []
    true_sig = []   # sinal "verdadeiro" sem ruído (referência)

    for i in range(N_SAMPLES):
        reading = sensor.next_reading()
        raw = reading.raw_percent
        raw_sig.append(raw * 100)                    # converte para % (0-100 range visual)
        ma_sig.append(ma.update(raw) * 100)
        kf_sig.append(kf.update(raw) * 100)
        true_sig.append((BASE_CONC + i * RAMP_RATE) * 100)  # sinal ideal sem ruído

    raw_arr  = np.array(raw_sig)
    ma_arr   = np.array(ma_sig)
    kf_arr   = np.array(kf_sig)
    true_arr = np.array(true_sig)

    # ─── Métricas de erro ─────────────────────────────────────────────
    # Ignora as primeiras N amostras de aquecimento do MA
    warmup = MA_WINDOW
    raw_mae  = np.mean(np.abs(raw_arr[warmup:] - true_arr[warmup:]))
    ma_mae   = np.mean(np.abs(ma_arr[warmup:]  - true_arr[warmup:]))
    kf_mae   = np.mean(np.abs(kf_arr[warmup:]  - true_arr[warmup:]))
    raw_rmse = np.sqrt(np.mean((raw_arr[warmup:] - true_arr[warmup:]) ** 2))
    ma_rmse  = np.sqrt(np.mean((ma_arr[warmup:]  - true_arr[warmup:]) ** 2))
    kf_rmse  = np.sqrt(np.mean((kf_arr[warmup:]  - true_arr[warmup:]) ** 2))

    # ── Métricas de redução de ruído (sinal constante, cenário justo) ──
    rng2 = np.random.default_rng(42)
    TRUE_CONST = 1.5
    ma2 = MovingAverageFilter(window_size=MA_WINDOW)
    kf2 = KalmanFilter1D(process_variance=KF_Q, measurement_variance=KF_R,
                         initial_estimate=TRUE_CONST)
    raw2_err, ma2_err, kf2_err = [], [], []
    for _ in range(N_SAMPLES):
        z = TRUE_CONST + rng2.normal(0, NOISE_STD)
        raw2_err.append(abs(z - TRUE_CONST))
        ma2_err.append(abs(ma2.update(z) - TRUE_CONST))
        kf2_err.append(abs(kf2.update(z) - TRUE_CONST))
    skip = MA_WINDOW
    raw2_mae = np.mean(raw2_err[skip:])
    ma2_mae  = np.mean(ma2_err[skip:])
    kf2_mae  = np.mean(kf2_err[skip:])

    print("\n" + "=" * 62)
    print("  SafeGas Monitor — Comparação de Filtros (Etapa 4)")
    print("=" * 62)
    print(f"  Cenário 1 (Rampa): RAMP_UP | ruído σ={NOISE_STD:.2f} | {N_SAMPLES} amostras")
    print(f"  Nota: filtros introduzem LAG em rampas → MAE maior é esperado")
    print(f"\n  {'Filtro':<16} {'MAE':>8}  {'RMSE':>8}  Observação")
    print(f"  {'-'*55}")
    print(f"  {'Bruto':<16} {raw_mae:>8.2f}  {raw_rmse:>8.2f}")
    print(f"  {'Média Móvel':<16} {ma_mae:>8.2f}  {ma_rmse:>8.2f}  lag={MA_WINDOW//2} amostras")
    print(f"  {'Kalman':<16} {kf_mae:>8.2f}  {kf_rmse:>8.2f}  lag depende de Q/R")
    print(f"\n  Cenário 2 (Constante + ruído): σ={NOISE_STD:.2f} — métricas de ruído puras")
    print(f"\n  {'Filtro':<16} {'MAE':>8}  Redução de ruído")
    print(f"  {'-'*42}")
    print(f"  {'Bruto':<16} {raw2_mae:>8.4f}  (referência)")
    print(f"  {'Média Móvel':<16} {ma2_mae:>8.4f}  {100*(1-ma2_mae/raw2_mae):.1f}% melhor")
    print(f"  {'Kalman':<16} {kf2_mae:>8.4f}  {100*(1-kf2_mae/raw2_mae):.1f}% melhor")
    print("=" * 62)

    # ─── Plot ─────────────────────────────────────────────────────────
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(14, 10))
    fig.suptitle(
        "SafeGas Monitor — Comparação de Filtros Digitais\n"
        f"Cenário: Vazamento crescente CH₄ | Ruído σ={NOISE_STD:.2f} | {N_SAMPLES}s @ 1 Hz",
        fontsize=13, fontweight="bold", y=0.98,
    )

    gs = gridspec.GridSpec(3, 1, hspace=0.45, figure=fig)

    # ── Painel 1: Sinal bruto ──────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(t_axis, raw_arr,  color="#E74C3C", lw=0.9, alpha=0.7, label="Sinal bruto")
    ax1.plot(t_axis, true_arr, color="#2C3E50", lw=1.5, ls="--",   label="Sinal real (referência)")
    ax1.set_title("Sinal Bruto (com ruído gaussiano)", fontsize=11)
    ax1.set_ylabel("Concentração CH₄ (%)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.set_ylim(bottom=0)

    # ── Painel 2: Filtros comparados ───────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    ax2.plot(t_axis, raw_arr, color="#E74C3C", lw=0.6, alpha=0.4, label="Bruto")
    ax2.plot(t_axis, ma_arr,  color="#F39C12", lw=1.8, label=f"Média Móvel (N={MA_WINDOW})")
    ax2.plot(t_axis, kf_arr,  color="#27AE60", lw=1.8, label=f"Kalman (Q={KF_Q:.0e}, R={KF_R})")
    ax2.plot(t_axis, true_arr,color="#2C3E50", lw=1.5, ls="--",   label="Sinal real")
    ax2.set_title("Comparação dos Filtros", fontsize=11)
    ax2.set_ylabel("Concentração CH₄ (%)")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.set_ylim(bottom=0)

    # ── Painel 3: Erro de estimação ────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    error_raw = raw_arr - true_arr
    error_ma  = ma_arr  - true_arr
    error_kf  = kf_arr  - true_arr
    ax3.axhline(0, color="#2C3E50", lw=1.0, ls="--", alpha=0.5)
    ax3.plot(t_axis, error_raw, color="#E74C3C", lw=0.6, alpha=0.4, label="Erro bruto")
    ax3.plot(t_axis, error_ma,  color="#F39C12", lw=1.5, label=f"Erro MA  (MAE={ma_mae:.4f})")
    ax3.plot(t_axis, error_kf,  color="#27AE60", lw=1.5, label=f"Erro KF  (MAE={kf_mae:.4f})")
    ax3.set_title("Erro de Estimação (filtrado − real)", fontsize=11)
    ax3.set_ylabel("Erro (% v/v)")
    ax3.set_xlabel("Tempo (s)")
    ax3.legend(loc="upper right", fontsize=9)

    # Anotação de limiares LEL (contexto do SafeGas)
    lel_ch4 = 5.0   # % v/v
    for ax in [ax1, ax2]:
        ax.axhline(lel_ch4, color="#C0392B", lw=1.2, ls=":", alpha=0.6)
        ax.text(N_SAMPLES * 0.98, lel_ch4 + 0.1, "LEL CH₄",
                ha="right", fontsize=8, color="#C0392B")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    plt.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")
    print(f"\n  Gráfico salvo em: {OUTPUT_PATH}\n")
    return OUTPUT_PATH, {"raw_mae": raw_mae, "ma_mae": ma_mae, "kf_mae": kf_mae,
                          "raw_rmse": raw_rmse, "ma_rmse": ma_rmse, "kf_rmse": kf_rmse}


if __name__ == "__main__":
    run()
