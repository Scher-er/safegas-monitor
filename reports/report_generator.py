"""
Fachada para geração de laudos técnicos em LaTeX/PDF e gráficos de incidentes.
"""

from reports.latex.report_generator import LatexReportGenerator
from reports.charts.chart_generator import IncidentChartGenerator

__all__ = [
    "LatexReportGenerator",
    "IncidentChartGenerator",
]
