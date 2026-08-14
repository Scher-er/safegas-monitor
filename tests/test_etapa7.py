"""
SafeGas Monitor — Testes da Etapa 7 (Geração de Laudos LaTeX)
=============================================================
Testa:
  1. _latex_escape: caracteres especiais corretamente escapados
  2. IncidentChartGenerator: PNG gerado com histórico real
  3. LatexReportGenerator.generate(): .tex criado, estrutura válida
  4. Conteúdo do .tex: seções, equações, dados do incidente
  5. PipelineHandler: laudo gerado automaticamente no evento CRITICAL
  6. Robustez: gerador não derruba o servidor em caso de erro
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import tempfile
import shutil
from datetime import datetime, timezone

from config.data_contracts import (
    TelemetryPacket, GasReading, ProcessedReading, IncidentRecord
)
from config.settings import GAS_CONFIG
from central_command.lel.lel_calculator import LELCalculator, LELResult
from central_command.pipeline_handler import PipelineHandler
from reports.charts.chart_generator import IncidentChartGenerator
from reports.latex.report_generator import (
    LatexReportGenerator, _latex_escape, _fmt_float, _fmt_risk_level,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_processed(
    device_id="EPI-TEX",
    risk_ratio=65.0,
    alert_level="CRITICAL",
    ch4_filt=3.25,
    co_filt=2.0,
) -> ProcessedReading:
    """Cria ProcessedReading de nível CRITICAL para testes do gerador."""
    lel_ch4 = GAS_CONFIG["CH4"]["lel_percent"]
    lel_co  = GAS_CONFIG["CO"]["lel_percent"]
    return ProcessedReading(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id=device_id,
        worker_id="F-042",
        location_id="LOC-001",
        temperature_c=32.5,
        readings=[
            GasReading(
                gas_id="CH4",
                raw_ppm=ch4_filt * 10_000,
                raw_percent=ch4_filt,
                filtered_percent=ch4_filt,
                lel_contribution=ch4_filt / lel_ch4,
            ),
            GasReading(
                gas_id="CO",
                raw_ppm=co_filt * 10_000,
                raw_percent=co_filt,
                filtered_percent=co_filt,
                lel_contribution=co_filt / lel_co,
            ),
        ],
        lel_mix_percent=100.0 / (ch4_filt / lel_ch4 + co_filt / lel_co) if (ch4_filt > 0 or co_filt > 0) else float("inf"),
        risk_ratio_percent=risk_ratio,
        alert_level=alert_level,
        filter_used="kalman",
    )


def _make_lel_result(processed: ProcessedReading) -> LELResult:
    calc = LELCalculator()
    return calc.calculate(processed.readings, temperature_c=processed.temperature_c)


def _make_history(n=30, device_id="EPI-TEX") -> list[ProcessedReading]:
    """Cria histórico crescente (simula escalonamento NORMAL → CRITICAL)."""
    history = []
    for i in range(n):
        frac = i / n   # 0.0 → 1.0
        ch4 = frac * 4.0   # 0 → 4.0% v/v
        co  = frac * 1.5
        risk = (ch4 / 5.0 + co / 12.5) * 100.0

        if risk < 10.0:    level = "NORMAL"
        elif risk < 25.0:  level = "ATTENTION"
        elif risk < 50.0:  level = "WARNING"
        else:              level = "CRITICAL"

        if i == 0:
            # Evita divisão por zero no primeiro ponto (todos zerados)
            history.append(_make_processed(
                device_id=device_id,
                risk_ratio=0.0,
                alert_level="NORMAL",
                ch4_filt=0.001,  # traço mínimo
                co_filt=0.001,
            ))
            continue
        history.append(_make_processed(
            device_id=device_id,
            risk_ratio=risk,
            alert_level=level,
            ch4_filt=ch4,
            co_filt=co,
        ))
    return history


# ─── Testes de utilidades ─────────────────────────────────────────────────────

def test_latex_escape_special_chars():
    """Caracteres especiais LaTeX devem ser escapados corretamente."""
    cases = [
        ("texto normal",          "texto normal"),
        ("EPI&001",               r"EPI\&001"),
        ("100%",                  r"100\%"),
        ("valor$100",             r"valor\$100"),
        ("chave{abc}",            r"chave\{abc\}"),
        ("underscore_id",         r"underscore\_id"),
        ("hash#123",              r"hash\#123"),
    ]
    for input_str, expected in cases:
        result = _latex_escape(input_str)
        assert result == expected, (
            f"_latex_escape({input_str!r}) = {result!r} ≠ {expected!r}"
        )
    print(f"  [OK] _latex_escape: {len(cases)} casos corretos")


def test_fmt_float_comma_decimal():
    """_fmt_float deve usar vírgula como separador decimal."""
    assert _fmt_float(3.14159, 2) == "3,14"
    assert _fmt_float(100.0, 0) == "100"
    assert _fmt_float(0.0005, 4) == "0,0005"
    assert _fmt_float(float("inf"), 2) == r"$\infty$"
    print("  [OK] _fmt_float: separador decimal correto")


def test_fmt_risk_level_colors():
    """_fmt_risk_level deve retornar comandos LaTeX com cores."""
    for level in ["NORMAL", "ATTENTION", "WARNING", "CRITICAL"]:
        result = _fmt_risk_level(level)
        assert r"\text" in result or "\\" in result, \
            f"{level} não tem formatação LaTeX"
    assert "red" in _fmt_risk_level("CRITICAL")
    print("  [OK] _fmt_risk_level: cores corretas para todos os níveis")


# ─── Testes IncidentChartGenerator ───────────────────────────────────────────

def test_chart_generator_creates_png():
    """IncidentChartGenerator deve criar um arquivo PNG válido."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_charts_")
    try:
        history = _make_history(40)
        out_path = os.path.join(tmp_dir, "test_chart.png")

        result = IncidentChartGenerator.generate(
            history=history,
            output_path=out_path,
            device_id="EPI-TEX",
            incident_timestamp=history[-1].timestamp,
        )

        assert result is not None, "generate() retornou None"
        assert os.path.exists(out_path), "Arquivo PNG não foi criado"
        size = os.path.getsize(out_path)
        assert size > 10_000, f"PNG muito pequeno ({size} bytes) — provavelmente corrompido"
        print(f"  [OK] PNG criado: {out_path} ({size // 1024} KB)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_chart_generator_empty_history():
    """Histórico vazio deve retornar None sem lançar exceção."""
    result = IncidentChartGenerator.generate(
        history=[],
        output_path="/tmp/should_not_exist.png",
        device_id="EPI-EMPTY",
    )
    assert result is None
    print("  [OK] Histórico vazio retorna None sem exceção")


def test_chart_generator_single_reading():
    """Histórico com apenas 1 leitura deve gerar PNG sem erros."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_single_")
    try:
        p = _make_processed()
        out_path = os.path.join(tmp_dir, "single.png")
        result = IncidentChartGenerator.generate(
            history=[p],
            output_path=out_path,
            device_id="EPI-TEX",
        )
        assert result is not None
        assert os.path.exists(out_path)
        print(f"  [OK] PNG com 1 leitura: {os.path.getsize(out_path) // 1024} KB")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Testes LatexReportGenerator ─────────────────────────────────────────────

def test_report_generator_creates_tex():
    """generate() deve criar um arquivo .tex no diretório configurado."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_reports_")
    tex_dir  = os.path.join(tmp_dir, "latex")
    chart_dir = os.path.join(tmp_dir, "charts")
    try:
        gen = LatexReportGenerator(
            reports_dir=tex_dir,
            charts_dir=chart_dir,
            compile_pdf=False,     # pdflatex pode não estar disponível nos testes
        )
        processed = _make_processed()
        lel       = _make_lel_result(processed)
        history   = _make_history(25)

        incident = gen.generate(processed, lel, history)

        assert isinstance(incident, IncidentRecord)
        assert incident.incident_id is not None
        assert incident.latex_report_path is not None
        assert os.path.exists(incident.latex_report_path), \
            f".tex não encontrado: {incident.latex_report_path}"

        size = os.path.getsize(incident.latex_report_path)
        assert size > 1000, f".tex muito pequeno ({size} bytes)"
        print(
            f"  [OK] .tex criado: {os.path.basename(incident.latex_report_path)} "
            f"({size // 1024} KB)"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_report_tex_content_sections():
    """O .tex gerado deve conter todas as seções esperadas do laudo."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_content_")
    try:
        gen = LatexReportGenerator(
            reports_dir=os.path.join(tmp_dir, "latex"),
            charts_dir=os.path.join(tmp_dir, "charts"),
            compile_pdf=False,
        )
        processed = _make_processed(device_id="EPI-CONTEUDO")
        lel       = _make_lel_result(processed)
        incident  = gen.generate(processed, lel, _make_history(20))

        with open(incident.latex_report_path, "r", encoding="utf-8") as f:
            tex = f.read()

        # Verifica estrutura do documento
        required = [
            r"\documentclass",          # é um documento LaTeX
            r"\begin{document}",
            r"\end{document}",
            "Dados do Incidente",       # Seção 1
            "Leituras dos Sensores",    # Seção 2
            "Le Chatelier",             # Seção 3
            "Zabetakis",                # equação de correção
            r"\begin{equation}",        # equações matemáticas
            "Hist",                     # Seção 4 (histórico)
            "Recomendadas",             # Seção 5 (ações recomendadas)
            "EPI-CONTEUDO",             # device_id no laudo
            "F-042",                    # worker_id
            "LOC-001",                  # location_id
            r"\fancyhf",               # cabeçalho/rodapé (do fancyhdr)
        ]

        missing = [s for s in required if s not in tex]
        assert not missing, f"Conteúdo faltando no .tex: {missing}"
        print(f"  [OK] Estrutura do .tex: todas as {len(required)} seções presentes")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_report_tex_device_id_escaped():
    """device_id com caractere especial deve ser escapado no .tex."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_escape_")
    try:
        gen = LatexReportGenerator(
            reports_dir=os.path.join(tmp_dir, "latex"),
            charts_dir=os.path.join(tmp_dir, "charts"),
            compile_pdf=False,
        )
        # device_id com underscore (caractere especial LaTeX)
        processed = _make_processed(device_id="EPI_UNIT_01")
        lel = _make_lel_result(processed)
        incident = gen.generate(processed, lel, [processed])

        with open(incident.latex_report_path, "r", encoding="utf-8") as f:
            tex = f.read()

        # Underscore deve aparecer escapado no LaTeX
        assert r"EPI\_UNIT\_01" in tex, \
            "Underscore não foi escapado no device_id"
        # Não deve aparecer sem escapar (causaria erro de compilação)
        # Nota: EPI_UNIT_01 pode aparecer no comentário do topo (não escapado)
        # então verificamos apenas que a versão escapada está lá
        print("  [OK] device_id com underscore corretamente escapado no .tex")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_report_incident_record_fields():
    """IncidentRecord retornado deve ter todos os campos preenchidos."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_record_")
    try:
        gen = LatexReportGenerator(
            reports_dir=os.path.join(tmp_dir, "latex"),
            charts_dir=os.path.join(tmp_dir, "charts"),
            compile_pdf=False,
        )
        processed = _make_processed(device_id="EPI-REC", risk_ratio=78.3)
        lel = _make_lel_result(processed)
        incident = gen.generate(processed, lel, [processed])

        assert incident.incident_id != ""
        assert incident.device_id == "EPI-REC"
        assert incident.worker_id == "F-042"
        assert incident.peak_risk_ratio == processed.risk_ratio_percent
        assert incident.latex_report_path.endswith(".tex")
        assert incident.resolved_at is None   # incidente novo, não resolvido
        print(
            f"  [OK] IncidentRecord: id={incident.incident_id[:8]}... "
            f"device={incident.device_id} R={incident.peak_risk_ratio:.1f}%"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_report_chart_embedded_in_tex():
    """Se o PNG foi criado, deve ser referenciado no .tex com \\includegraphics."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_chart_embed_")
    try:
        gen = LatexReportGenerator(
            reports_dir=os.path.join(tmp_dir, "latex"),
            charts_dir=os.path.join(tmp_dir, "charts"),
            compile_pdf=False,
        )
        processed = _make_processed()
        lel = _make_lel_result(processed)
        # Histórico suficiente para gerar chart
        history = _make_history(20)
        incident = gen.generate(processed, lel, history)

        with open(incident.latex_report_path, "r", encoding="utf-8") as f:
            tex = f.read()

        # Verifica que o gráfico foi embutido
        assert r"\includegraphics" in tex, \
            "\\includegraphics não encontrado: gráfico não foi embutido"
        assert ".png" in tex, "Referência ao PNG não encontrada no .tex"
        print("  [OK] Gráfico PNG embutido no .tex via \\includegraphics")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Testes PipelineHandler + Etapa 7 ────────────────────────────────────────

def test_pipeline_generates_report_on_critical():
    """PipelineHandler deve gerar laudo automaticamente em evento CRITICAL."""
    tmp_dir = tempfile.mkdtemp(prefix="safegas_test_ph_")
    try:
        # Substitui os diretórios de saída pelo temporário
        import config.settings as stt
        original_reports = stt.REPORTS_OUTPUT_DIR
        original_charts  = stt.CHARTS_OUTPUT_DIR
        stt.REPORTS_OUTPUT_DIR = os.path.join(tmp_dir, "latex")
        stt.CHARTS_OUTPUT_DIR  = os.path.join(tmp_dir, "charts")
        os.makedirs(stt.REPORTS_OUTPUT_DIR, exist_ok=True)
        os.makedirs(stt.CHARTS_OUTPUT_DIR, exist_ok=True)

        handler = PipelineHandler(
            filter_mode="moving_avg",
            verbose_output=False,
            enable_mongo=False,
        )

        # Injeta diretórios temporários no gerador do handler
        handler._report_generator = LatexReportGenerator(
            reports_dir=stt.REPORTS_OUTPUT_DIR,
            charts_dir=stt.CHARTS_OUTPUT_DIR,
            compile_pdf=False,
        )

        # Alimenta amostras crescentes até CRITICAL (CH4=2.5% → R=50%)
        for _ in range(20):
            pkt = TelemetryPacket(
                packet_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                device_id="EPI-PH7",
                worker_id="F-042",
                location_id="LOC-001",
                temperature_c=25.0,
                readings=[GasReading(gas_id="CH4", raw_ppm=25000, raw_percent=2.5)],
            )
            result = handler(pkt)

        # Verifica que o laudo foi gerado
        tex_files = [f for f in os.listdir(stt.REPORTS_OUTPUT_DIR)
                     if f.endswith(".tex")]
        assert len(tex_files) >= 1, \
            f"Nenhum .tex gerado em {stt.REPORTS_OUTPUT_DIR}"
        assert handler.stats["incidents_generated"] >= 1

        print(
            f"  [OK] Laudo automático gerado: {tex_files[0]} | "
            f"incidentes={handler.stats['incidents_generated']}"
        )

        # Restaura settings
        stt.REPORTS_OUTPUT_DIR = original_reports
        stt.CHARTS_OUTPUT_DIR  = original_charts
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_pipeline_report_generator_exception_does_not_crash():
    """Erro no gerador não deve derrubar o PipelineHandler."""
    handler = PipelineHandler(
        filter_mode="moving_avg",
        verbose_output=False,
        enable_mongo=False,
    )
    # Substitui o gerador por um que sempre lança exceção
    class BrokenGenerator:
        def generate(self, *a, **kw):
            raise RuntimeError("Falha simulada no gerador de laudos!")
    handler._report_generator = BrokenGenerator()

    # Deve processar normalmente — _generate_report captura a exceção
    pkt = TelemetryPacket(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id="EPI-ERR",
        worker_id="F-042",
        location_id="LOC-001",
        temperature_c=25.0,
        readings=[GasReading(gas_id="CH4", raw_ppm=25000, raw_percent=2.5)],
    )
    # Aquece o filtro — sem propagar a exceção
    result = None
    try:
        for _ in range(20):
            result = handler(pkt)
    except Exception as e:
        assert False, f"Exceção propagada indevidamente: {e}"

    assert result is not None
    assert result.alert_level == "CRITICAL"
    print("  [OK] Exceção no gerador não derruba o PipelineHandler")


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_all():
    print("\n" + "=" * 65)
    print("  SafeGas Monitor — Testes da Etapa 7 (Laudos LaTeX)")
    print("=" * 65)

    groups = [
        ("Utilitários LaTeX", [
            test_latex_escape_special_chars,
            test_fmt_float_comma_decimal,
            test_fmt_risk_level_colors,
        ]),
        ("IncidentChartGenerator", [
            test_chart_generator_creates_png,
            test_chart_generator_empty_history,
            test_chart_generator_single_reading,
        ]),
        ("LatexReportGenerator", [
            test_report_generator_creates_tex,
            test_report_tex_content_sections,
            test_report_tex_device_id_escaped,
            test_report_incident_record_fields,
            test_report_chart_embedded_in_tex,
        ]),
        ("PipelineHandler + Etapa 7 (Integração)", [
            test_pipeline_generates_report_on_critical,
            test_pipeline_report_generator_exception_does_not_crash,
        ]),
    ]

    total_passed, total_tests = 0, 0
    for group_name, tests in groups:
        print(f"\n-- {group_name} " + "-" * max(1, 52 - len(group_name)))
        for t in tests:
            total_tests += 1
            try:
                print(f"\n[TESTE] {t.__name__}")
                t()
                total_passed += 1
            except Exception as e:
                print(f"  [FALHOU] {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'=' * 65}")
    print(f"  Resultado: {total_passed}/{total_tests} testes passaram")
    print("=" * 65 + "\n")
    return total_passed == total_tests


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    success = run_all()
    sys.exit(0 if success else 1)
