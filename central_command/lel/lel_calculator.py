"""
SafeGas Monitor — Calculador de LEL de Misturas — Etapa 5
==========================================================
Implementa:
  1. Correção de LEL por temperatura (Zabetakis, 1965)
  2. Equação de Le Chatelier para misturas de gases inflamáveis
  3. Cálculo do fator de risco R = (C_mix / LEL_mix) × 100%

Equações:
  ┌─────────────────────────────────────────────────────────┐
  │  Correção de Zabetakis (temperatura):                   │
  │    LEL_T = LEL_25 × [1 - 0.08 × (T - 25) / 100]        │
  │                                                         │
  │  Le Chatelier (misturas):                               │
  │             100                                         │
  │  LEL_mix = ─────────────────                            │
  │             Σ  (Ci / LEL_i,T)                           │
  │              i                                          │
  │                                                         │
  │  Fator de risco (%):                                    │
  │    R = (C_mix / LEL_mix) × 100                          │
  │  onde C_mix = Σ Ci                                      │
  └─────────────────────────────────────────────────────────┘

Referências:
  - Zabetakis, M. G. (1965). Flammability characteristics of
    combustible gases and vapors. Bureau of Mines Bulletin 627.
  - Le Chatelier, H. (1891). Estimation of firedamp by flammability
    limits. Annales des Mines, 19(8), 388-395.
  - NFPA 325 (2019). Fire Hazard Properties of Flammable Liquids,
    Gases, and Volatile Solids.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
from dataclasses import dataclass
from typing import Optional

from config.settings import GAS_CONFIG
from config.data_contracts import GasReading

log = logging.getLogger(__name__)

# Coeficiente de temperatura de Zabetakis (°C⁻¹)
_ZABETAKIS_COEFF = 0.08 / 100.0   # 0.0008 por °C acima de 25°C
_ZABETAKIS_REF_T = 25.0            # temperatura de referência (°C)

# Concentração mínima para incluir um gás no cálculo de Le Chatelier
# (evita divisão por LEL com valor próximo de zero)
_MIN_CONCENTRATION_PERCENT = 1e-6  # 0.001 ppm — limiar de detecção


# ─── Resultado do cálculo ─────────────────────────────────────────────────────

@dataclass
class LELResult:
    """Resultado completo do cálculo de risco de explosão."""
    lel_mix_percent: float      # LEL_mix da mistura (% v/v) — Le Chatelier
    c_mix_percent: float        # concentração total dos gases inflamáveis (% v/v)
    risk_ratio_percent: float   # R = (C_mix / LEL_mix) × 100  (% do LEL_mix)
    temperature_c: float        # temperatura usada na correção de Zabetakis
    gases_contributing: list    # lista de gas_ids que contribuíram para o cálculo
    corrections_applied: dict   # {gas_id: LEL_T corrigido} para rastreabilidade

    @property
    def is_explosive_range(self) -> bool:
        """True se a mistura está dentro do intervalo explosivo (R ≥ 100%)."""
        return self.risk_ratio_percent >= 100.0

    def __repr__(self) -> str:
        return (
            f"LELResult(LEL_mix={self.lel_mix_percent:.4f}%, "
            f"C_mix={self.c_mix_percent:.4f}%, "
            f"R={self.risk_ratio_percent:.2f}%, "
            f"T={self.temperature_c:.1f}°C)"
        )


# ─── Calculador ───────────────────────────────────────────────────────────────

class LELCalculator:
    """
    Calcula o Limite Inferior de Explosividade de misturas de gases.

    Aplica a equação de Le Chatelier com correção de temperatura
    de Zabetakis sobre os valores filtrados das leituras do EPI.

    Uso:
        calc = LELCalculator()
        result = calc.calculate(readings, temperature_c=32.0)
        print(result.risk_ratio_percent)   # % do LEL_mix atingido
    """

    def __init__(self, min_concentration: float = _MIN_CONCENTRATION_PERCENT):
        """
        Args:
            min_concentration: concentração mínima (% v/v) para incluir
                               um gás no cálculo. Evita artefatos numéricos.
        """
        self._min_conc = min_concentration
        log.debug("LELCalculator inicializado (min_conc=%.2e%%)", min_concentration)

    # ------------------------------------------------------------------
    def _zabetakis_correction(self, lel_25: float, temperature_c: float) -> float:
        """
        Corrige o LEL de um gás para a temperatura ambiente atual.

        LEL_T = LEL_25 × [1 − 0.08 × (T − 25) / 100]

        Acima de 25°C o LEL diminui (mistura fica mais perigosa).
        Abaixo de 25°C o LEL aumenta (mistura fica mais segura).

        Args:
            lel_25:       LEL à temperatura de referência (25°C), em % v/v
            temperature_c:temperatura ambiente atual (°C)

        Returns:
            LEL corrigido para temperature_c, em % v/v
        """
        correction_factor = 1.0 - _ZABETAKIS_COEFF * (temperature_c - _ZABETAKIS_REF_T)
        # Garante que o LEL corrigido seja positivo e não trivial
        lel_t = lel_25 * max(correction_factor, 0.1)
        log.debug(
            "Zabetakis: LEL_25=%.3f%%, T=%.1f°C, fator=%.4f → LEL_T=%.4f%%",
            lel_25, temperature_c, correction_factor, lel_t,
        )
        return lel_t

    # ------------------------------------------------------------------
    def _le_chatelier(
        self,
        concentrations: dict[str, float],
        corrected_lels: dict[str, float],
    ) -> Optional[float]:
        """
        Aplica a equação de Le Chatelier para calcular LEL_mix.

            LEL_mix = 100 / Σ(Ci / LEL_i,T)

        Args:
            concentrations:  {gas_id: Ci em % v/v}
            corrected_lels:  {gas_id: LEL_i,T em % v/v}

        Returns:
            LEL_mix em % v/v, ou None se nenhum gás estiver presente.
        """
        summation = 0.0
        for gas_id, ci in concentrations.items():
            lel_t = corrected_lels.get(gas_id)
            if lel_t and lel_t > 0 and ci > self._min_conc:
                summation += ci / lel_t

        if summation <= 0.0:
            return None  # nenhum gás inflamável detectável

        return 100.0 / summation

    # ------------------------------------------------------------------
    def calculate(
        self,
        readings: list[GasReading],
        temperature_c: float = 25.0,
        use_filtered: bool = True,
    ) -> LELResult:
        """
        Calcula o risco de explosão da mistura de gases.

        Args:
            readings:     lista de GasReading (com filtered_percent se disponível)
            temperature_c:temperatura ambiente atual para correção de Zabetakis
            use_filtered: True → usa filtered_percent; False → usa raw_percent

        Returns:
            LELResult com todos os campos calculados.
        """
        # ── Extrai concentrações e aplica Zabetakis ───────────────────
        concentrations: dict[str, float] = {}
        corrected_lels: dict[str, float] = {}
        corrections_log: dict[str, float] = {}
        gases_contributing: list[str] = []

        for r in readings:
            if r.gas_id not in GAS_CONFIG:
                log.warning("Gás '%s' não está em GAS_CONFIG — ignorado.", r.gas_id)
                continue

            conc = r.filtered_percent if (use_filtered and r.filtered_percent is not None) \
                   else r.raw_percent

            if conc < self._min_conc:
                continue  # concentração negligível, pula

            lel_25 = GAS_CONFIG[r.gas_id]["lel_percent"]
            lel_t  = self._zabetakis_correction(lel_25, temperature_c)

            concentrations[r.gas_id]  = conc
            corrected_lels[r.gas_id]  = lel_t
            corrections_log[r.gas_id] = round(lel_t, 6)
            gases_contributing.append(r.gas_id)

        # ── Calcula C_mix e LEL_mix ───────────────────────────────────
        c_mix = sum(concentrations.values())

        if not gases_contributing:
            # Nenhum gás detectável → risco zero
            log.debug("Nenhum gás acima do limiar de detecção.")
            return LELResult(
                lel_mix_percent=float("inf"),
                c_mix_percent=0.0,
                risk_ratio_percent=0.0,
                temperature_c=temperature_c,
                gases_contributing=[],
                corrections_applied={},
            )

        lel_mix = self._le_chatelier(concentrations, corrected_lels)

        # ── Fator de risco R (% do LEL_mix) ──────────────────────────
        # Fórmula correta: R = Σ(Ci/LELi,T) × 100
        # (algebricamente equivalente a C_mix/LEL_mix × 100 apenas quando
        #  os gases têm LELs idênticos, mas a fórmula Σ é a canônica
        #  para Le Chatelier e funciona corretamente para gás único)
        summation = sum(
            ci / corrected_lels[gid]
            for gid, ci in concentrations.items()
            if corrected_lels.get(gid, 0) > 0
        )
        risk_ratio = summation * 100.0

        # LEL_mix calculado por Le Chatelier (100/Σ)
        if lel_mix is None or lel_mix <= 0:
            log.warning("LEL_mix inválido calculado. Concentrações: %s", concentrations)
            lel_mix = float("inf")

        result = LELResult(
            lel_mix_percent=round(lel_mix, 6),
            c_mix_percent=round(c_mix, 6),
            risk_ratio_percent=round(risk_ratio, 4),
            temperature_c=temperature_c,
            gases_contributing=gases_contributing,
            corrections_applied=corrections_log,
        )

        log.info(
            "LEL calculado: C_mix=%.4f%%, LEL_mix=%.4f%%, R=%.2f%%, T=%.1f°C, gases=%s",
            c_mix, lel_mix, risk_ratio, temperature_c, gases_contributing,
        )
        return result
