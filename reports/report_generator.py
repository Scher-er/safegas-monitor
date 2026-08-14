# SafeGas Monitor — Gerador de Laudos LaTeX (ESQUELETO — Etapa 7)
# =================================================================

class LatexReportGenerator:
    """
    Gera automaticamente laudos técnicos em LaTeX quando um incidente
    crítico é detectado.
    
    IMPLEMENTAR NA ETAPA 7:
    - Buscar dados dos últimos 15 minutos no MongoDB
    - Gerar gráfico de dispersão (concentração × tempo) via Matplotlib
    - Preencher template LaTeX com dados do incidente
    - Salvar o .tex no diretório de laudos
    
    Estrutura do laudo:
        \documentclass{article}
        - Cabeçalho: data/hora, funcionário, local, EPI
        - Tabela: leituras por gás (bruto, filtrado, LEL%)
        - Gráfico: dispersão concentração × tempo (15 min)
        - Análise: LEL_mix no pico, nível de risco
        - Rodapé: recomendações de evacuação / ações tomadas
    """

    def __init__(self, output_dir: str, charts_dir: str):
        raise NotImplementedError("Implementar na Etapa 7")

    def generate(self, incident_id: str, telemetry_data: list,
                 worker_info: dict, location_info: dict) -> str:
        """
        Gera o laudo e retorna o caminho do arquivo .tex.
        
        Args:
            incident_id:    ID único do incidente
            telemetry_data: lista de ProcessedReadings dos últimos 15 min
            worker_info:    dados do funcionário (do SQLite)
            location_info:  dados do local (do SQLite)
        
        Returns:
            Caminho absoluto do arquivo .tex gerado.
        """
        raise NotImplementedError("Implementar na Etapa 7")

    def _plot_chart(self, telemetry_data: list, output_path: str):
        """Gera gráfico de dispersão e salva como PDF/PNG."""
        raise NotImplementedError("Implementar na Etapa 7")

    def _fill_template(self, template_vars: dict) -> str:
        """Preenche o template LaTeX com as variáveis do incidente."""
        raise NotImplementedError("Implementar na Etapa 7")
