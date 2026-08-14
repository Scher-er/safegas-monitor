# SafeGas Monitor — Calculador de LEL (ESQUELETO — Etapa 5)
# ===========================================================

class LELCalculator:
    """
    Calcula o Limite Inferior de Explosividade de misturas de gases
    usando a Equação de Le Chatelier com correção termodinâmica.
    
    IMPLEMENTAR NA ETAPA 5:
    
    Equação de Le Chatelier:
        LEL_mix = 100 / Σ(Ci / LELi)
    
    Onde:
        Ci   = concentração do gás i em % v/v (do total de gases combustíveis)
        LELi = LEL tabelado do gás i puro (% v/v)
    
    Correção termodinâmica de Zabetakis:
        LEL_T = LEL_25°C × (1 - 0.08 × (T - 25) / 100)
    
    Índice de risco:
        R = (C_mix / LEL_mix) × 100%
    
    Limiares de alerta:
        R < 10%  → NORMAL
        10% ≤ R < 25% → ATTENTION
        25% ≤ R < 50% → WARNING
        R ≥ 50%  → CRITICAL
    """

    def __init__(self, gas_config: dict):
        """
        Args:
            gas_config: dicionário com LEL de cada gás (de config/settings.py)
        """
        raise NotImplementedError("Implementar na Etapa 5")

    def calculate(self, concentrations: dict, temperature_c: float) -> dict:
        """
        Calcula o risco de explosão da mistura.
        
        Args:
            concentrations: {gas_id: filtered_percent} para cada gás presente
            temperature_c: temperatura atual (para correção termodinâmica)
        
        Returns:
            dict com: lel_mix, risk_ratio_percent, alert_level, contributions
        """
        raise NotImplementedError("Implementar na Etapa 5")

    def _apply_temperature_correction(self, lel_25c: float, temperature_c: float) -> float:
        """Aplica correção de Zabetakis ao LEL."""
        raise NotImplementedError("Implementar na Etapa 5")

    def _classify_alert(self, risk_ratio_percent: float) -> str:
        """Classifica o nível de risco: NORMAL | ATTENTION | WARNING | CRITICAL."""
        raise NotImplementedError("Implementar na Etapa 5")
