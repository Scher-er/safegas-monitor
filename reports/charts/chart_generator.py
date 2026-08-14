"""
SafeGas Monitor — Gerador de Gráficos para Laudos — Etapa 7
=============================================================
Gera gráficos matplotlib (PNG) a partir do histórico de leituras
de um EPI, para serem embutidos no laudo LaTeX.

Conteúdo do gráfico:
  Painel 1 — Concentração (% v/v): bruto e filtrado por gás
             Linhas horizontais nos limiares de alerta (10/25/50% LEL)
  Painel 2 — Fator de risco R (% do LEL_mix) ao longo do tempo
             Zonas coloridas: verde/amarelo/laranja/vermelho

Uso:
    path = IncidentChartGenerator.generate(
        history=list_of_processed_readings,
        output_path="reports/charts/incident_001.png",
    )
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
from typing import Optional

from config.settings import (
    GAS_CONFIG,
    ALERT_LOW_THRESHOLD,
    ALERT_MEDIUM_THRESHOLD,
    ALERT_CRITICAL_THRESHOLD,
)
from config.data_contracts import ProcessedReading

log = logging.getLogger(__name__)

# Paleta de cores por gás (consistente com docs/filter_comparison.png)
_GAS_COLORS = {
    "CH4":   "#E74C3C",   # vermelho
    "CO":    "#F39C12",   # laranja
    "H2S":   "#8E44AD",   # roxo
    "C3H8":  "#27AE60",   # verde
    "C4H10": "#2980B9",   # azul
}
_DEFAULT_COLOR = "#7F8C8D"

# Cores das zonas de risco
_ZONE_COLORS = {
    "NORMAL":    ("#2ECC71", 0.10),   # verde claro
    "ATTENTION": ("#F1C40F", 0.12),   # amarelo
    "WARNING":   ("#E67E22", 0.12),   # laranja
    "CRITICAL":  ("#E74C3C", 0.12),   # vermelho
}


class IncidentChartGenerator:
    """
    Gera imagem PNG com dois painéis para laudos técnicos de incidente.
    """

    @staticmethod
    def generate(
        history: list[ProcessedReading],
        output_path: str,
        device_id: str = "",
        incident_timestamp: str = "",
    ) -> Optional[str]:
        """
        Gera o gráfico e salva em output_path.

        Args:
            history:             lista de ProcessedReadings (ordem cronológica)
            output_path:         caminho absoluto para o PNG de saída
            device_id:           ID do EPI (para o título)
            incident_timestamp:  timestamp do incidente (para o título)

        Returns:
            Caminho absoluto do arquivo gerado, ou None em caso de erro.
        """
        if not history:
            log.warning("Histórico vazio — gráfico não gerado.")
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            import matplotlib.gridspec as gridspec
        except ImportError:
            log.error("matplotlib não instalado — gráfico não gerado.")
            return None

        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

            n = len(history)
            t_axis = list(range(n))

            # ── Coleta dados por gás ──────────────────────────────────
            gases_present = sorted({
                r.gas_id
                for p in history
                for r in p.readings
                if r.filtered_percent and r.filtered_percent > 1e-6
            })

            gas_raw:      dict[str, list] = {g: [] for g in gases_present}
            gas_filtered: dict[str, list] = {g: [] for g in gases_present}
            risk_series:  list[float] = []

            for p in history:
                reading_map = {r.gas_id: r for r in p.readings}
                for g in gases_present:
                    r = reading_map.get(g)
                    gas_raw[g].append(r.raw_percent * 100 if r else 0.0)
                    gas_filtered[g].append(
                        (r.filtered_percent or r.raw_percent) * 100 if r else 0.0
                    )
                risk_series.append(p.risk_ratio_percent)

            # ── Layout ───────────────────────────────────────────────
            plt.style.use("seaborn-v0_8-whitegrid")
            fig = plt.figure(figsize=(14, 9))
            fig.patch.set_facecolor("#FAFAFA")

            title_ts = incident_timestamp[11:19] if incident_timestamp else ""
            fig.suptitle(
                f"SafeGas Monitor — Laudo Técnico de Incidente\n"
                f"Dispositivo: {device_id}   |   Evento: {incident_timestamp[:10]} {title_ts}",
                fontsize=13, fontweight="bold", y=0.99,
            )

            gs = gridspec.GridSpec(2, 1, hspace=0.40, figure=fig,
                                   height_ratios=[2, 1])

            # ── Painel 1: Concentrações ───────────────────────────────
            ax1 = fig.add_subplot(gs[0])

            for g in gases_present:
                color = _GAS_COLORS.get(g, _DEFAULT_COLOR)
                ax1.plot(t_axis, gas_raw[g],
                         color=color, lw=0.7, alpha=0.35, ls="--")
                ax1.plot(t_axis, gas_filtered[g],
                         color=color, lw=1.8, label=f"{g} (filtrado)")

            # Limiares de alerta por gás (linha LEL individual)
            for g in gases_present:
                if g in GAS_CONFIG:
                    lel_val = GAS_CONFIG[g]["lel_percent"] * 100   # em %
                    ax1.axhline(
                        lel_val,
                        color=_GAS_COLORS.get(g, _DEFAULT_COLOR),
                        lw=0.8, ls=":", alpha=0.5,
                    )
                    ax1.text(
                        n * 0.99, lel_val + 0.05,
                        f"LEL {g}",
                        ha="right", fontsize=7,
                        color=_GAS_COLORS.get(g, _DEFAULT_COLOR),
                    )

            ax1.set_title("Concentração dos Gases (% v/v)", fontsize=11)
            ax1.set_ylabel("Concentração (% v/v)")
            ax1.set_ylim(bottom=0)
            ax1.legend(loc="upper left", fontsize=8, ncol=min(len(gases_present), 3))
            # Linha pontilhada vertical no instante final (incidente)
            ax1.axvline(n - 1, color="#C0392B", lw=1.5, ls="--", alpha=0.7)
            ax1.text(n - 1.2, ax1.get_ylim()[1] * 0.95,
                     "CRÍTICO", ha="right", fontsize=8, color="#C0392B",
                     fontweight="bold")

            # ── Painel 2: Fator de risco R ────────────────────────────
            ax2 = fig.add_subplot(gs[1], sharex=ax1)

            # Zonas coloridas
            ax2.axhspan(0, ALERT_LOW_THRESHOLD,
                        color="#2ECC71", alpha=0.12, label="NORMAL")
            ax2.axhspan(ALERT_LOW_THRESHOLD, ALERT_MEDIUM_THRESHOLD,
                        color="#F1C40F", alpha=0.15, label="ATENÇÃO")
            ax2.axhspan(ALERT_MEDIUM_THRESHOLD, ALERT_CRITICAL_THRESHOLD,
                        color="#E67E22", alpha=0.15, label="ALERTA")
            ax2.axhspan(ALERT_CRITICAL_THRESHOLD, max(max(risk_series) * 1.1, 60),
                        color="#E74C3C", alpha=0.12, label="CRÍTICO")

            ax2.plot(t_axis, risk_series, color="#2C3E50", lw=2.0,
                     label="R = Σ(Cᵢ/LELᵢ)×100%")
            ax2.axhline(ALERT_CRITICAL_THRESHOLD,
                        color="#C0392B", lw=1.2, ls="--", alpha=0.8)

            ax2.set_title("Fator de Risco R (% do LEL_mix)", fontsize=11)
            ax2.set_ylabel("R (%)")
            ax2.set_xlabel(f"Amostras (n={n}, @ {1} Hz)")
            ax2.legend(loc="upper left", fontsize=8, ncol=4)
            ax2.set_ylim(bottom=0)

            plt.savefig(output_path, dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            plt.close(fig)

            log.info("Gráfico de incidente salvo: %s", output_path)
            return output_path

        except Exception as e:
            log.error("Erro ao gerar gráfico de incidente: %s", e, exc_info=True)
            return None
