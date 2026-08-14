"""
SafeGas Monitor — Gerador de Laudos LaTeX — Etapa 7
=====================================================
Gera laudos técnicos automatizados no padrão ABNT quando um evento
CRITICAL é detectado pela Central de Comando.

Fluxo:
  1. AlertManager detecta CRITICAL → chama on_critical callback
  2. PipelineHandler chama LatexReportGenerator.generate()
  3. Gerador cria gráfico PNG (IncidentChartGenerator)
  4. Gerador preenche template LaTeX com dados do incidente
  5. Salva .tex em reports/latex/<incident_id>.tex
  6. Tenta compilar com pdflatex (opcional — falha graciosamente)
  7. Cria IncidentRecord e insere no MongoDB

Estrutura do laudo:
  ┌─────────────────────────────────────────────────────────┐
  │  Cabeçalho institucional (SafeGas Monitor / UNIVAP)     │
  │  1. Dados do Incidente (EPI, funcionário, local, hora)  │
  │  2. Resumo das Leituras (tabela de gases filtrados)     │
  │  3. Cálculo LEL (tabela Le Chatelier por gás)           │
  │  4. Histórico de Alertas (últimos N eventos)            │
  │  5. Gráfico de Concentração e Risco (PNG embutido)      │
  │  6. Rodapé: observações, assinatura, timestamp          │
  └─────────────────────────────────────────────────────────┘
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
import uuid
import subprocess
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    REPORTS_OUTPUT_DIR,
    CHARTS_OUTPUT_DIR,
    GAS_CONFIG,
    REPORT_LOOKBACK_MINUTES,
)
from config.data_contracts import ProcessedReading, IncidentRecord
from central_command.lel.lel_calculator import LELResult
from reports.charts.chart_generator import IncidentChartGenerator

log = logging.getLogger(__name__)

# Cabeçalho do projeto (para o laudo)
_INSTITUTION = "UNIVAP — Universidade do Vale do Paraíba"
_PROJECT     = "SafeGas Monitor — Projetos em Engenharia I"
_AUTHORS     = "Equipe SafeGas (Engenharia da Computação)"


# ─── Utilitários de escape LaTeX ──────────────────────────────────────────────

def _latex_escape(text: str) -> str:
    """
    Escapa caracteres especiais do LaTeX em texto arbitrário.
    Essencial para device_id, nomes e locais que podem ter caracteres especiais.
    """
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
    ]
    for char, replacement in replacements:
        text = text.replace(char, replacement)
    return text


def _fmt_risk_level(level: str) -> str:
    """Formata o nível de alerta com cor LaTeX."""
    colors = {
        "NORMAL":    r"\textcolor{green!60!black}{NORMAL}",
        "ATTENTION": r"\textcolor{orange}{ATEN\c{C}\~AO}",
        "WARNING":   r"\textcolor{orange!80!red}{ALERTA}",
        "CRITICAL":  r"\textbf{\textcolor{red}{CR\'ITICO}}",
    }
    return colors.get(level, level)


def _fmt_float(v: float, decimals: int = 4) -> str:
    """Formata float para exibição no LaTeX (vírgula como separador decimal)."""
    if v == float("inf"):
        return r"$\infty$"
    formatted = f"{v:.{decimals}f}"
    return formatted.replace(".", ",")


# ─── Template LaTeX ───────────────────────────────────────────────────────────

def _build_latex(
    incident_id: str,
    processed: ProcessedReading,
    lel: LELResult,
    history: list[ProcessedReading],
    chart_path: Optional[str],
    generated_at: str,
) -> str:
    """
    Monta o documento LaTeX completo.

    Args:
        incident_id:  UUID do incidente
        processed:    ProcessedReading do evento CRITICAL
        lel:          LELResult do cálculo de risco
        history:      histórico recente (para tabela de alertas)
        chart_path:   caminho absoluto do PNG (ou None)
        generated_at: timestamp de geração do laudo

    Returns:
        String com o documento LaTeX completo.
    """
    # ── Dados básicos ──────────────────────────────────────────────────
    dev_id   = _latex_escape(processed.device_id)
    worker   = _latex_escape(processed.worker_id)
    location = _latex_escape(processed.location_id)
    ts_raw   = processed.timestamp
    ts_br    = f"{ts_raw[8:10]}/{ts_raw[5:7]}/{ts_raw[:4]} {ts_raw[11:19]} UTC"
    temp     = _fmt_float(processed.temperature_c, 1)
    risk_str = _fmt_float(processed.risk_ratio_percent, 2)
    lel_mix  = _fmt_float(lel.lel_mix_percent, 4)
    risk_level_fmt = _fmt_risk_level(processed.alert_level)

    # ── Tabela de leituras por gás ─────────────────────────────────────
    readings_rows = ""
    for r in processed.readings:
        gas_name = GAS_CONFIG.get(r.gas_id, {}).get("name", r.gas_id)
        lel_individual = GAS_CONFIG.get(r.gas_id, {}).get("lel_percent", "--")
        raw_pct   = _fmt_float(r.raw_percent * 100, 4)
        filt_pct  = _fmt_float((r.filtered_percent or r.raw_percent) * 100, 4)
        contrib   = _fmt_float(r.lel_contribution * 100, 2) if r.lel_contribution else "0,00"
        readings_rows += (
            f"        {_latex_escape(r.gas_id)} & {_latex_escape(gas_name)} & "
            f"{lel_individual} & {raw_pct} & {filt_pct} & {contrib}\\% \\\\\n"
        )

    # ── Tabela de histórico de alertas ────────────────────────────────
    history_rows = ""
    alert_icons = {
        "NORMAL":    "--",
        "ATTENTION": "!",
        "WARNING":   "!!",
        "CRITICAL":  "!!!",
    }
    recent = history[-20:]  # últimos 20 eventos
    for p in recent:
        ts_h = p.timestamp[11:19]
        icon = alert_icons.get(p.alert_level, "?")
        r_val = _fmt_float(p.risk_ratio_percent, 2)
        history_rows += (
            f"        {ts_h} UTC & "
            f"{_fmt_risk_level(p.alert_level)} & "
            f"{icon} & "
            f"{r_val}\\% \\\\\n"
        )

    # ── Gráfico (se disponível) ────────────────────────────────────────
    # No LaTeX, o caminho usa / mesmo no Windows, e é relativo ao .tex
    chart_include = ""
    if chart_path and os.path.exists(chart_path):
        # Converte para caminho relativo ao diretório do .tex
        chart_latex_path = chart_path.replace("\\", "/")
        chart_include = (
            r"""
\section{Gr\'afico de Concentra\c{c}\~ao e Risco}

\begin{figure}[H]
  \centering
  \includegraphics[width=\linewidth]{""" + chart_latex_path + r"""}
  \caption{Concentra\c{c}\~ao dos gases (bruto e filtrado) e fator de risco $R = \sum (C_i/\mathrm{LEL}_{i,T}) \times 100\%$ ao longo do tempo. Linha tracejada vermelha indica o instante do evento cr\'itico.}
  \label{fig:incident}
\end{figure}"""
        )

    # ── Documento completo ─────────────────────────────────────────────
    doc = rf"""% SafeGas Monitor — Laudo Técnico de Incidente
% Gerado automaticamente em {generated_at}
% ID do Incidente: {incident_id}
% NÃO EDITAR MANUALMENTE — arquivo gerado pelo sistema

\documentclass[a4paper,12pt]{{article}}

% Pacotes essenciais
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage[brazil]{{babel}}
\usepackage{{geometry}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{graphicx}}
\usepackage{{float}}
\usepackage{{xcolor}}
\usepackage{{amsmath}}
\usepackage{{fancyhdr}}
\usepackage{{hyperref}}
\usepackage{{microtype}}
\usepackage{{array}}
\usepackage{{colortbl}}

\geometry{{
    a4paper,
    top=2.5cm, bottom=2.5cm,
    left=3.0cm, right=2.5cm
}}

% Cabeçalho e rodapé
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\small\textbf{{SafeGas Monitor}} --- Laudo Técnico de Incidente}}
\fancyhead[R]{{\small ID: {_latex_escape(incident_id[:8])}...}}
\fancyfoot[C]{{\small P\'agina \thepage}}
\fancyfoot[R]{{\small Gerado em: {_latex_escape(generated_at[:19])}}}

\hypersetup{{
    colorlinks=true,
    linkcolor=blue,
    urlcolor=blue,
    pdftitle={{SafeGas Monitor - Laudo de Incidente}},
    pdfauthor={{SafeGas Monitor System}},
}}

\definecolor{{alertred}}{{RGB}}{{192,57,43}}
\definecolor{{alertorange}}{{RGB}}{{230,126,34}}
\definecolor{{alertyellow}}{{RGB}}{{241,196,15}}
\definecolor{{safegreen}}{{RGB}}{{39,174,96}}
\definecolor{{headerblue}}{{RGB}}{{41,128,185}}
\definecolor{{lightgray}}{{RGB}}{{245,245,245}}


\begin{{document}}

% ─── Cabeçalho institucional ─────────────────────────────────────────────────
\begin{{center}}
    {{\Large\bfseries\color{{headerblue}} LAUDO TÉCNICO DE INCIDENTE}}\\[4pt]
    {{\large\bfseries Sistema SafeGas Monitor}}\\[2pt]
    {{\normalsize {_latex_escape(_INSTITUTION)}}}\\[2pt]
    {{\normalsize {_latex_escape(_PROJECT)}}}\\[2pt]
    {{\small {_latex_escape(_AUTHORS)}}}
\end{{center}}

\vspace{{4pt}}
\noindent\rule{{\linewidth}}{{1.5pt}}
\vspace{{6pt}}

% ─── 1. Dados do Incidente ───────────────────────────────────────────────────
\section{{Dados do Incidente}}

\begin{{table}}[H]
\centering
\rowcolors{{2}}{{lightgray}}{{white}}
\begin{{tabular}}{{>{{\ }}l<{{\ }} >{{\ }}l<{{\ }}}}
    \toprule
    \textbf{{Campo}} & \textbf{{Valor}} \\
    \midrule
    ID do Incidente    & \texttt{{{_latex_escape(incident_id)}}} \\
    Timestamp          & {ts_br} \\
    Dispositivo EPI    & \texttt{{{dev_id}}} \\
    Funcion\'ario      & \texttt{{{worker}}} \\
    Local              & {location} \\
    Temperatura amb.   & {temp}\textdegree C \\
    \midrule
    N\'ivel de Alerta  & {risk_level_fmt} \\
    Fator de Risco $R$ & \textbf{{{risk_str}\%}} do $\mathrm{{LEL}}_{{mix}}$ \\
    $\mathrm{{LEL}}_{{mix}}$ (Le Chatelier) & {lel_mix}\% (v/v) \\
    \bottomrule
\end{{tabular}}
\caption{{Dados do evento cr\'itico detectado.}}
\end{{table}}

% ─── 2. Leituras dos Sensores ────────────────────────────────────────────────
\section{{Leituras dos Sensores no Momento do Incidente}}

\begin{{table}}[H]
\centering
\rowcolors{{2}}{{lightgray}}{{white}}
\begin{{tabular}}{{llrrrr}}
    \toprule
    \textbf{{ID}} & \textbf{{G\'as}} & \textbf{{LEL (\%)}} &
    \textbf{{Bruto (\%)}} & \textbf{{Filtrado (\%)}} &
    \textbf{{Contribui\c{{c}}\~ao LEL}} \\
    \midrule
{readings_rows}    \bottomrule
\end{{tabular}}
\caption{{Leituras dos sensores no instante do evento. Filtro: Kalman 1D.
         Contribui\c{{c}}\~ao calculada por Le Chatelier: $C_i / \mathrm{{LEL}}_{{i,T}}$.}}
\end{{table}}

% ─── 3. Cálculo LEL (Le Chatelier + Zabetakis) ───────────────────────────────
\section{{C\'alculo do $\mathrm{{LEL}}_{{mix}}$ (Le Chatelier com Corre\c{{c}}\~ao de Zabetakis)}}

\subsection*{{Equa\c{{c}}\~oes Aplicadas}}

\begin{{equation}}
    \mathrm{{LEL}}_{{i,T}} = \mathrm{{LEL}}_{{25}} \times
    \left[1 - \frac{{0{{,}}08 \times (T - 25)}}{{100}}\right]
    \quad \text{{(Zabetakis, 1965)}}
\end{{equation}}

\begin{{equation}}
    \mathrm{{LEL}}_{{mix}} = \frac{{100}}{{\displaystyle\sum_{{i}}
    \frac{{C_i}}{{\mathrm{{LEL}}_{{i,T}}}}}}
    \quad \text{{(Le Chatelier, 1891)}}
\end{{equation}}

\begin{{equation}}
    R = \sum_i \frac{{C_i}}{{\mathrm{{LEL}}_{{i,T}}}} \times 100\%
    = \mathbf{{{risk_str}\%}}
    \quad [\text{{LIMIAR CR\'ITICO: 50\%}}]
\end{{equation}}

\begin{{table}}[H]
\centering
\begin{{tabular}}{{lr}}
    \toprule
    \textbf{{Par\^ametro}} & \textbf{{Valor}} \\
    \midrule
    Gases contribuintes    & {_latex_escape(", ".join(lel.gases_contributing) or "Nenhum")} \\
    Temperatura de refer.  & {_fmt_float(lel.temperature_c, 1)}\textdegree C \\
    $C_{{mix}}$ total      & {_fmt_float(lel.c_mix_percent, 4)}\% (v/v) \\
    $\mathrm{{LEL}}_{{mix}}$ & {lel_mix}\% (v/v) \\
    Fator de risco $R$     & \textbf{{{risk_str}\%}} \\
    Classifica\c{{c}}\~ao  & {risk_level_fmt} \\
    \bottomrule
\end{{tabular}}
\caption{{Resumo do c\'alculo de risco com corre\c{{c}}\~ao de temperatura.}}
\end{{table}}

% ─── 4. Histórico de Alertas ─────────────────────────────────────────────────
\section{{Hist\'orico de Alertas (\'Ultimos {len(recent)} Eventos)}}\

\begin{{longtable}}{{lllr}}
    \toprule
    \textbf{{Hora (UTC)}} & \textbf{{N\'ivel}} & \textbf{{Grav.}} & \textbf{{R (\%)}} \\
    \midrule
    \endfirsthead
    \multicolumn{{4}}{{c}}{{\small\itshape Continuação da tabela anterior}} \\
    \midrule
    \endhead
    \midrule
    \multicolumn{{4}}{{r}}{{\small\itshape Continua na pr\'oxima p\'agina}} \\
    \endfoot
    \bottomrule
    \endlastfoot
{history_rows}
\end{{longtable}}

{chart_include}

% ─── 5. Ações Recomendadas ───────────────────────────────────────────────────
\section{{A\c{{c}}\~oes Recomendadas}}

\begin{{enumerate}}
    \item \textbf{{Evacua\c{{c}}\~ao imediata}} da \'area de risco pelo funcion\'ario
          \texttt{{{worker}}}.
    \item \textbf{{Notifica\c{{c}}\~ao}} do Corpo de Bombeiros e equipe de emerg\^encia.
    \item \textbf{{Bloqueio de acesso}} ao local \texttt{{{location}}} at\'e avalia\c{{c}}\~ao
          t\'ecnica presencial.
    \item \textbf{{Calibra\c{{c}}\~ao}} do dispositivo \texttt{{{dev_id}}} ap\'os o incidente.
    \item \textbf{{Registro formal}} do ocorrido no sistema de gest\~ao de EHS.
\end{{enumerate}}

% ─── Rodapé ──────────────────────────────────────────────────────────────────
\vspace{{20pt}}
\noindent\rule{{\linewidth}}{{0.4pt}}

\begin{{center}}
\small
Laudo gerado automaticamente pelo SafeGas Monitor em\\
\textbf{{{_latex_escape(generated_at[:19])} UTC}}\\[6pt]
\textit{{Este documento é gerado com fins acadêmicos no âmbito da disciplina
Projetos em Engenharia I — UNIVAP. Não substitui laudo técnico oficial.}}
\end{{center}}

\vspace{{24pt}}
\noindent
\begin{{tabular}}{{p{{6cm}} p{{6cm}}}}
    \underline{{\hspace{{6cm}}}} & \underline{{\hspace{{6cm}}}} \\[2pt]
    Responsável Técnico & Supervisor de Campo \\
    Data: \_\_\_ / \_\_\_ / \_\_\_\_ & Data: \_\_\_ / \_\_\_ / \_\_\_\_ \\
\end{{tabular}}

\end{{document}}
"""
    return doc


# ─── Gerador Principal ────────────────────────────────────────────────────────

class LatexReportGenerator:
    """
    Gera laudos técnicos LaTeX para eventos CRITICAL.

    Uso típico (via PipelineHandler):
        generator = LatexReportGenerator()
        incident = generator.generate(processed, lel_result, history)
        # retorna IncidentRecord com o caminho do .tex gerado
    """

    def __init__(
        self,
        reports_dir: str = REPORTS_OUTPUT_DIR,
        charts_dir: str = CHARTS_OUTPUT_DIR,
        compile_pdf: bool = True,
    ):
        """
        Args:
            reports_dir: diretório de saída dos arquivos .tex
            charts_dir:  diretório de saída dos gráficos PNG
            compile_pdf: se True, tenta compilar o .tex com pdflatex
        """
        self._reports_dir = reports_dir
        self._charts_dir  = charts_dir
        self._compile_pdf = compile_pdf
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(charts_dir, exist_ok=True)
        log.info(
            "LatexReportGenerator pronto: tex=%s charts=%s compile_pdf=%s",
            reports_dir, charts_dir, compile_pdf,
        )

    # ------------------------------------------------------------------
    def generate(
        self,
        processed: ProcessedReading,
        lel_result: LELResult,
        history: list[ProcessedReading],
    ) -> IncidentRecord:
        """
        Gera o laudo completo para um evento CRITICAL.

        Etapas:
          1. Gera gráfico PNG do histórico
          2. Monta o documento LaTeX
          3. Salva o .tex
          4. Opcionalmente compila com pdflatex
          5. Retorna IncidentRecord

        Args:
            processed:  ProcessedReading com alert_level == "CRITICAL"
            lel_result: resultado do LELCalculator para este pacote
            history:    histórico recente de leituras do mesmo EPI

        Returns:
            IncidentRecord com os caminhos do .tex gerado.
        """
        incident_id  = str(uuid.uuid4())
        generated_at = datetime.now(timezone.utc).isoformat()

        log.info(
            "Gerando laudo: incidente=%s device=%s R=%.2f%%",
            incident_id[:8], processed.device_id, lel_result.risk_ratio_percent,
        )

        # 1. Gráfico PNG
        chart_filename = f"chart_{incident_id[:8]}.png"
        chart_path = os.path.join(self._charts_dir, chart_filename)
        chart_path = IncidentChartGenerator.generate(
            history=history or [processed],
            output_path=chart_path,
            device_id=processed.device_id,
            incident_timestamp=processed.timestamp,
        )

        # 2. Documento LaTeX
        tex_content = _build_latex(
            incident_id=incident_id,
            processed=processed,
            lel=lel_result,
            history=history or [processed],
            chart_path=chart_path,
            generated_at=generated_at,
        )

        # 3. Salva .tex
        tex_filename = f"incident_{incident_id[:8]}.tex"
        tex_path = os.path.join(self._reports_dir, tex_filename)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        log.info("Laudo .tex salvo: %s", tex_path)
        print(f"\n  >> Laudo LaTeX gerado: {tex_path}")

        # 4. Compila com pdflatex (opcional)
        pdf_path = tex_path.replace(".tex", ".pdf")
        if self._compile_pdf:
            pdf_path = self._compile(tex_path) or tex_path

        # 5. IncidentRecord
        incident = IncidentRecord(
            incident_id=incident_id,
            triggered_at=processed.timestamp,
            device_id=processed.device_id,
            worker_id=processed.worker_id,
            location_id=processed.location_id,
            peak_risk_ratio=processed.risk_ratio_percent,
            latex_report_path=tex_path,
        )
        return incident

    # ------------------------------------------------------------------
    def _compile(self, tex_path: str) -> Optional[str]:
        """
        Tenta compilar o .tex com pdflatex.
        Falha silenciosamente se pdflatex não estiver instalado.

        Returns:
            Caminho do .pdf gerado, ou None se falhou.
        """
        try:
            result = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-output-directory", os.path.dirname(tex_path),
                    tex_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            pdf_path = tex_path.replace(".tex", ".pdf")
            if result.returncode == 0 and os.path.exists(pdf_path):
                log.info("PDF compilado com sucesso: %s", pdf_path)
                print(f"  >> PDF compilado: {pdf_path}")
                return pdf_path
            else:
                log.warning(
                    "pdflatex retornou código %d. Laudo disponível como .tex.",
                    result.returncode,
                )
                return None
        except FileNotFoundError:
            log.info("pdflatex não encontrado — laudo disponível como .tex.")
            print("  >> pdflatex não instalado. Compile o .tex manualmente.")
            return None
        except subprocess.TimeoutExpired:
            log.warning("pdflatex timeout — laudo disponível como .tex.")
            return None
        except Exception as e:
            log.warning("Erro ao compilar PDF: %s", e)
            return None
