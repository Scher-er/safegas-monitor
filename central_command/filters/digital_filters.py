# SafeGas Monitor — Filtros Digitais (ESQUELETO — Etapa 4)
# ==========================================================

class MovingAverageFilter:
    """
    Filtro de Média Móvel simples.
    
    IMPLEMENTAR NA ETAPA 4:
    - Manter buffer circular de tamanho N
    - Retornar média das últimas N amostras
    """

    def __init__(self, window_size: int):
        raise NotImplementedError("Implementar na Etapa 4")

    def update(self, value: float) -> float:
        """Adiciona nova amostra e retorna a média filtrada."""
        raise NotImplementedError("Implementar na Etapa 4")

    def reset(self):
        raise NotImplementedError("Implementar na Etapa 4")


class KalmanFilter1D:
    """
    Filtro de Kalman unidimensional para séries temporais escalares.
    
    IMPLEMENTAR NA ETAPA 4:
    - Equações de predição: x̂_{k|k-1} = x̂_{k-1}, P_{k|k-1} = P_{k-1} + Q
    - Equações de atualização: K = P/(P+R), x̂ = x̂ + K*(z - x̂), P = (1-K)*P
    """

    def __init__(self, process_variance: float, measurement_variance: float,
                 initial_estimate: float = 0.0):
        raise NotImplementedError("Implementar na Etapa 4")

    def update(self, measurement: float) -> float:
        """Processa nova medição e retorna o estado estimado."""
        raise NotImplementedError("Implementar na Etapa 4")

    def reset(self, initial_estimate: float = 0.0):
        raise NotImplementedError("Implementar na Etapa 4")
