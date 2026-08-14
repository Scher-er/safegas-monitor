"""
SafeGas Monitor — Filtros Digitais — Etapa 4
=============================================
Implementa dois filtros para suavização do sinal bruto dos sensores:

  1. MovingAverageFilter  — Média Móvel Simples (SMA)
     Fórmula: C_MA(t) = (1/N) * Σ C(t-k),  k = 0..N-1

  2. KalmanFilter1D  — Filtro de Kalman Escalar
     Predição:   x̂_{k|k-1} = x̂_{k-1|k-1}
                 P_{k|k-1} = P_{k-1|k-1} + Q
     Atualização: K_k = P_{k|k-1} / (P_{k|k-1} + R)
                  x̂_{k|k} = x̂_{k|k-1} + K_k * (z_k - x̂_{k|k-1})
                  P_{k|k} = (1 - K_k) * P_{k|k-1}

Ambos os filtros mantêm estado interno entre chamadas — cada instância
deve ser criada por (device_id, gas_id) para preservar continuidade.

Referências:
  - Kalman, R. E. (1960). "A New Approach to Linear Filtering and
    Prediction Problems." ASME Journal of Basic Engineering.
  - Oppenheim & Schafer, "Discrete-Time Signal Processing", 3ed, cap. 5.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from collections import deque
from typing import Optional
import logging

from config.settings import (
    MOVING_AVG_WINDOW,
    KALMAN_PROCESS_VARIANCE,
    KALMAN_MEASUREMENT_VARIANCE,
)

log = logging.getLogger(__name__)


# ─── Filtro de Média Móvel Simples ────────────────────────────────────────────

class MovingAverageFilter:
    """
    Filtro de Média Móvel com buffer circular de tamanho N.

    Durante o período de aquecimento (menos de N amostras recebidas),
    a média é calculada sobre as amostras disponíveis — sem descarte.

    Exemplo:
        f = MovingAverageFilter(window_size=5)
        for v in [1, 2, 3, 4, 5, 6]:
            print(f.update(v))   # 1, 1.5, 2, 2.5, 3, 4
    """

    def __init__(self, window_size: int = MOVING_AVG_WINDOW):
        """
        Args:
            window_size: número de amostras na janela deslizante (N ≥ 1)
        """
        if window_size < 1:
            raise ValueError(f"window_size deve ser ≥ 1, recebido: {window_size}")

        self.window_size = window_size
        self._buffer: deque[float] = deque(maxlen=window_size)
        self._sum = 0.0     # soma acumulada para cálculo eficiente O(1)
        log.debug("MovingAverageFilter criado: N=%d", window_size)

    # ------------------------------------------------------------------
    def update(self, value: float) -> float:
        """
        Insere nova amostra e retorna a média filtrada.

        Args:
            value: nova leitura do sensor (% v/v ou qualquer escalar)

        Returns:
            Média das últimas N amostras (ou menos, se ainda no aquecimento)
        """
        # Se buffer cheio, subtrai o valor que vai sair
        if len(self._buffer) == self.window_size:
            self._sum -= self._buffer[0]

        self._buffer.append(value)
        self._sum += value

        return self._sum / len(self._buffer)

    # ------------------------------------------------------------------
    def reset(self, initial_value: Optional[float] = None) -> None:
        """
        Limpa o estado do filtro.

        Args:
            initial_value: se fornecido, pré-aquece o buffer com este valor
        """
        self._buffer.clear()
        self._sum = 0.0
        if initial_value is not None:
            for _ in range(self.window_size):
                self.update(initial_value)

    # ------------------------------------------------------------------
    @property
    def is_warmed_up(self) -> bool:
        """True quando o buffer está cheio (período de aquecimento encerrado)."""
        return len(self._buffer) == self.window_size

    @property
    def current_value(self) -> Optional[float]:
        """Última saída filtrada, ou None se o buffer estiver vazio."""
        if not self._buffer:
            return None
        return self._sum / len(self._buffer)

    def __repr__(self) -> str:
        return (
            f"MovingAverageFilter(N={self.window_size}, "
            f"amostras={len(self._buffer)}, "
            f"valor={self.current_value:.4f if self.current_value is not None else 'N/A'})"
        )


# ─── Filtro de Kalman Escalar (1D) ────────────────────────────────────────────

class KalmanFilter1D:
    """
    Filtro de Kalman para estimação de estado escalar contínuo.

    Ideal para sinais com ruído branco gaussiano — o caso exato
    do nosso simulador de sensores eletroquímicos.

    Parâmetros-chave:
      Q (process_variance):      ruído de processo. Valor maior → filtro
                                 mais ágil (acredita mais nas medições).
      R (measurement_variance):  ruído de medição. Valor maior → filtro
                                 mais suave (acredita menos nas medições).

    Regra prática:
      Q << R  → saída muito suave, mas lenta para rastrear mudanças reais.
      Q >> R  → saída ágil, mas pouco filtrada.
      Q ≈ R   → equilíbrio razoável para sensores industriais.
    """

    def __init__(
        self,
        process_variance: float = KALMAN_PROCESS_VARIANCE,
        measurement_variance: float = KALMAN_MEASUREMENT_VARIANCE,
        initial_estimate: float = 0.0,
        initial_error_covariance: float = 1.0,
    ):
        """
        Args:
            process_variance:        Q — variância do ruído de processo
            measurement_variance:    R — variância do ruído de medição
            initial_estimate:        x̂_0 — estimativa inicial do estado
            initial_error_covariance:P_0 — incerteza inicial (costuma-se
                                     usar um valor alto para convergência rápida)
        """
        if process_variance <= 0:
            raise ValueError("process_variance (Q) deve ser > 0")
        if measurement_variance <= 0:
            raise ValueError("measurement_variance (R) deve ser > 0")

        self._Q = process_variance
        self._R = measurement_variance

        # Estado interno
        self._x = initial_estimate         # estimativa atual x̂_{k|k}
        self._P = initial_error_covariance # covariância do erro P_{k|k}

        self._initialized = False
        self._sample_count = 0

        log.debug(
            "KalmanFilter1D criado: Q=%.2e, R=%.2e, x0=%.4f",
            process_variance, measurement_variance, initial_estimate,
        )

    # ------------------------------------------------------------------
    def update(self, measurement: float) -> float:
        """
        Processa uma nova medição e retorna o estado estimado.

        Etapas:
          1. Predição:   x̂_{k|k-1} = x̂_{k-1},  P_{k|k-1} = P_{k-1} + Q
          2. Ganho:      K = P_{k|k-1} / (P_{k|k-1} + R)
          3. Atualização:x̂_{k|k} = x̂_{k|k-1} + K * (z - x̂_{k|k-1})
                         P_{k|k} = (1 - K) * P_{k|k-1}

        Args:
            measurement: z_k — valor medido pelo sensor (% v/v ou qualquer escalar)

        Returns:
            x̂_{k|k} — estimativa filtrada do estado real
        """
        # Na primeira medição, inicializa com o valor observado
        if not self._initialized:
            self._x = measurement
            self._initialized = True
            self._sample_count += 1
            return self._x

        # ── Etapa de Predição ──────────────────────────────────────
        x_pred = self._x            # modelo: estado constante no curto prazo
        P_pred = self._P + self._Q  # incerteza cresce sem medição

        # ── Ganho de Kalman ────────────────────────────────────────
        K = P_pred / (P_pred + self._R)   # 0 ≤ K ≤ 1

        # ── Etapa de Atualização ───────────────────────────────────
        innovation = measurement - x_pred           # resíduo (inovação)
        self._x = x_pred + K * innovation           # nova estimativa
        self._P = (1.0 - K) * P_pred                # nova covariância

        self._sample_count += 1

        log.debug(
            "Kalman: z=%.4f, x̂=%.4f, K=%.4f, P=%.4e",
            measurement, self._x, K, self._P,
        )
        return self._x

    # ------------------------------------------------------------------
    def reset(self, initial_estimate: float = 0.0,
              initial_error_covariance: float = 1.0) -> None:
        """Reinicia o filtro para o estado inicial."""
        self._x = initial_estimate
        self._P = initial_error_covariance
        self._initialized = False
        self._sample_count = 0

    # ------------------------------------------------------------------
    @property
    def current_estimate(self) -> float:
        """Estimativa atual do estado x̂_{k|k}."""
        return self._x

    @property
    def kalman_gain(self) -> float:
        """
        Ganho de Kalman na última iteração (valor em [0,1]).
        K próximo de 1 → confia mais na medição.
        K próximo de 0 → confia mais no modelo.
        """
        if not self._initialized:
            return 0.0
        P_pred = self._P + self._Q
        return P_pred / (P_pred + self._R)

    @property
    def error_covariance(self) -> float:
        """Covariância do erro de estimação P_{k|k}."""
        return self._P

    def __repr__(self) -> str:
        return (
            f"KalmanFilter1D(Q={self._Q:.2e}, R={self._R:.2e}, "
            f"x̂={self._x:.4f}, P={self._P:.4e}, "
            f"amostras={self._sample_count})"
        )
