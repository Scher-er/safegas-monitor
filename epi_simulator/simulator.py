"""
SafeGas Monitor — Simulador de EPI (Etapa 2)
=============================================
Implementa a simulação de sensores eletroquímicos de gás com:
  - Sinal base configurável (constante, rampa ou senoidal)
  - Ruído branco gaussiano N(0, σ²) para emular instabilidade real
  - Temperatura ambiente simulada com variação aleatória
  - Geração contínua de TelemetryPackets prontos para transmissão

Uso standalone (sem rede):
    python -m epi_simulator.simulator

Referências:
  - Ruído gaussiano: OPPENHEIM & SCHAFER, Discrete-Time Signal Processing, 3ed.
  - Instabilidade de sensores: FIGARO Engineering, MQ-series sensor datasheet.
"""

import time
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable, Optional
from enum import Enum

import numpy as np

# Importações internas do projeto
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import (
    GAS_CONFIG,
    SIMULATION_BASE_CONCENTRATIONS,
    SIMULATION_NOISE_STD,
    TEMPERATURE_BASE_C,
    TEMPERATURE_NOISE_STD,
    SAMPLE_RATE_HZ,
)
from config.data_contracts import TelemetryPacket, GasReading

# ─── Logger do módulo ─────────────────────────────────────────────────────────
log = logging.getLogger(__name__)


# ─── Tipos de sinal base ──────────────────────────────────────────────────────
class SignalProfile(Enum):
    """Perfil do sinal de concentração base ao longo do tempo."""
    CONSTANT            = "constant"             # concentração fixa (cenário estável)
    RAMP_UP             = "ramp_up"              # vazamento crescente (emergência linear)
    RAMP_DOWN           = "ramp_down"            # dispersão após evacuação
    SINUSOIDAL          = "sinusoidal"           # oscilação periódica (ventilação)
    STEP                = "step"                 # degrau súbito (ruptura instantânea)
    DYNAMIC_LEAK        = "dynamic_leak"         # vazamento não-linear com turbulência e eddies
    STOCHASTIC_DRIFT    = "stochastic_drift"     # flutuações ambientais realistas (Ornstein-Uhlenbeck)
    CYCLIC_VENTING      = "cyclic_venting"       # acúmulo operacional com exaustão periódica
    INTERMITTENT_BURSTS = "intermittent_bursts"  # pulsos e micro-vazamentos intermitentes de válvulas


# ─── Sensor individual ────────────────────────────────────────────────────────
class GasSensorSimulator:
    """
    Simula um sensor eletroquímico/catalítico de gás com:
      - Ruído branco gaussiano N(0, σ²)
      - Difusão molecular e inércia do sensor (filtro passa-baixas de membrana)
      - Turbulência atmosférica convectiva e micro-rajadas (eddies)
      - Perfis temporais lineares, não-lineares e estocásticos

    A concentração resultante é limitada a [0, UEL] para realismo físico.
    """

    def __init__(
        self,
        gas_id: str,
        base_concentration: float = 0.0,
        noise_std: float = SIMULATION_NOISE_STD,
        profile: SignalProfile = SignalProfile.CONSTANT,
        ramp_rate: float = 0.001,           # % v/v por amostra (para RAMP_UP/DOWN)
        sine_amplitude: float = 0.05,       # amplitude da senoide (% v/v)
        sine_period_s: float = 60.0,        # período da senoide (segundos)
        step_at_sample: int = 30,           # amostra em que ocorre o degrau (STEP)
        step_target: float = 0.5,           # valor alvo após o degrau (% v/v)
        inertia_alpha: float = 1.0,         # taxa de resposta da membrana (1.0 = instantâneo, <1.0 = inércia física)
        peak_target: float = 2.5,           # valor de pico para DYNAMIC_LEAK (% v/v)
        leak_duration_samples: int = 120,   # amostras para atingir o pico
        leak_start_sample: int = 0,         # amostra em que inicia a escalada
        vent_period_s: float = 75.0,        # período do ciclo operacional com ventilação
        drift_theta: float = 0.08,          # velocidade de reversão à média (Ornstein-Uhlenbeck)
        drift_sigma: float = 0.003,         # volatilidade do ruído ambiental
        seed: Optional[int] = None,
    ):
        if gas_id not in GAS_CONFIG:
            raise ValueError(
                f"Gás '{gas_id}' não reconhecido. "
                f"Disponíveis: {list(GAS_CONFIG.keys())}"
            )

        self.gas_id     = gas_id
        self.gas_name   = GAS_CONFIG[gas_id]["name"]
        self.lel        = GAS_CONFIG[gas_id]["lel_percent"]
        self.uel        = GAS_CONFIG[gas_id]["uel_percent"]

        self._base      = base_concentration
        self._noise_std = noise_std
        self._profile   = profile
        self._ramp_rate = ramp_rate
        self._sine_amp  = sine_amplitude
        self._sine_period = sine_period_s
        self._step_at   = step_at_sample
        self._step_tgt  = step_target

        self._inertia_alpha = max(0.05, min(1.0, inertia_alpha))
        self._peak_target   = peak_target
        self._leak_duration = max(10, leak_duration_samples)
        self._leak_start    = leak_start_sample
        self._vent_period   = vent_period_s
        self._drift_theta   = drift_theta
        self._drift_sigma   = drift_sigma

        self._sample_count = 0
        self._rng = np.random.default_rng(seed)

        # Estados dinâmicos internos
        self._current_val = base_concentration
        self._turbulent_state = 0.0
        self._drift_state = base_concentration

        log.debug(
            "GasSensorSimulator criado: gas=%s, base=%.3f%%, σ=%.4f, profile=%s, inertia=%.2f",
            gas_id, base_concentration, noise_std, profile.value, self._inertia_alpha
        )

    # ------------------------------------------------------------------
    def _compute_base(self) -> float:
        """Calcula C_base(t) de acordo com o perfil configurado."""
        n = self._sample_count

        if self._profile == SignalProfile.CONSTANT:
            return self._base

        elif self._profile == SignalProfile.RAMP_UP:
            return self._base + n * self._ramp_rate

        elif self._profile == SignalProfile.RAMP_DOWN:
            return max(0.0, self._base - n * self._ramp_rate)

        elif self._profile == SignalProfile.SINUSOIDAL:
            period_samples = self._sine_period * SAMPLE_RATE_HZ
            return self._base + self._sine_amp * np.sin(2 * np.pi * n / period_samples)

        elif self._profile == SignalProfile.STEP:
            return self._step_tgt if n >= self._step_at else self._base

        elif self._profile == SignalProfile.DYNAMIC_LEAK:
            # Vazamento físico não-linear (S-Curve / cinética de expansão gasosa) + pluma turbulenta
            if n < self._leak_start:
                # Pré-vazamento: pequenas flutuações no baseline
                drift = self._rng.normal(0.0, self._drift_sigma)
                return max(0.0, self._base + drift)

            progress = min(1.0, max(0.0, (n - self._leak_start) / float(self._leak_duration)))
            # Transição sigmoidal suave (Hermite cubic)
            s_curve = progress * progress * (3.0 - 2.0 * progress)
            macro_trend = self._base + (self._peak_target - self._base) * s_curve

            # Dinâmica de vórtices turbulentos (convective eddies)
            # Decaimento autoregressivo com injeção estocástica proporcional à concentração
            eddy_noise = self._rng.normal(0.0, 0.035 * max(0.1, macro_trend))
            self._turbulent_state = 0.78 * self._turbulent_state + eddy_noise

            # Ocasional baforada/rajada de gás (puffs) típica de vazamentos sob pressão
            if self._rng.random() < 0.12 and progress > 0.1:
                puff = self._rng.uniform(0.02, 0.08) * macro_trend
                self._turbulent_state += puff

            return max(0.0, macro_trend + self._turbulent_state)

        elif self._profile == SignalProfile.STOCHASTIC_DRIFT:
            # Flutuação ambiental orgânica (Processo de Ornstein-Uhlenbeck)
            # Reversão contínua para self._base com perturbações de fluxo de ar
            dt = 1.0 / SAMPLE_RATE_HZ
            drift = self._drift_theta * (self._base - self._drift_state) * dt
            diff = self._drift_sigma * np.sqrt(dt) * self._rng.normal(0.0, 1.0)
            self._drift_state = max(0.001, self._drift_state + drift + diff)
            return self._drift_state

        elif self._profile == SignalProfile.CYCLIC_VENTING:
            # Operação industrial cíclica: emissão durante atividade e varredura por HVAC
            cycle_samples = self._vent_period * SAMPLE_RATE_HZ
            phase = (n % cycle_samples) / float(cycle_samples)
            if phase < 0.38:
                # Fase de acúmulo: elevação não-linear
                sub_p = phase / 0.38
                val = self._base + (self._peak_target - self._base) * (sub_p ** 1.6)
            else:
                # Fase de exaustão: decaimento exponencial rápido
                decay_p = (phase - 0.38) / 0.62
                val = self._base + (self._peak_target - self._base) * np.exp(-4.5 * decay_p)

            # Leve turbulência de ventilação
            turb = self._rng.normal(0.0, 0.008)
            return max(0.0, val + turb)

        elif self._profile == SignalProfile.INTERMITTENT_BURSTS:
            # Fugas transitórias intermitentes (ex: abertura de flanges ou alívio de linha)
            if self._rng.random() < 0.08:
                self._turbulent_state += self._rng.uniform(0.15, 0.45)
            self._turbulent_state *= 0.88 # decaimento rápido do pulso
            return max(0.0, self._base + self._turbulent_state)

        return self._base

    # ------------------------------------------------------------------
    def next_reading(self) -> GasReading:
        """
        Gera a próxima leitura do sensor.

        Returns:
            GasReading com campos raw_percent e raw_ppm preenchidos.
            Os campos filtered_* serão preenchidos pela Central (Etapa 4).
        """
        c_base = self._compute_base()

        # Adiciona ruído gaussiano: η ~ N(0, σ²)
        noise  = self._rng.normal(loc=0.0, scale=self._noise_std)
        c_inst = c_base + noise

        # Inércia física do sensor (filtro de resposta de difusão de membrana)
        if self._inertia_alpha < 1.0:
            self._current_val = (
                self._inertia_alpha * c_inst + (1.0 - self._inertia_alpha) * self._current_val
            )
            c_raw = self._current_val
        else:
            c_raw = c_inst

        # Limita ao intervalo físico válido [0, UEL]
        c_raw = float(np.clip(c_raw, 0.0, self.uel))

        # Converte % v/v → PPM  (1% = 10 000 PPM)
        ppm = c_raw * 10_000.0

        self._sample_count += 1

        return GasReading(
            gas_id=self.gas_id,
            raw_ppm=round(ppm, 2),
            raw_percent=round(c_raw, 6),
        )

    # ------------------------------------------------------------------
    def reset(self, base_concentration: Optional[float] = None):
        """Reinicia o sensor, opcionalmente alterando a concentração base."""
        self._sample_count = 0
        if base_concentration is not None:
            self._base = base_concentration
            self._current_val = base_concentration
            self._drift_state = base_concentration
        self._turbulent_state = 0.0
        log.debug("Sensor %s reiniciado.", self.gas_id)

    def __repr__(self) -> str:
        return (
            f"GasSensorSimulator(gas={self.gas_id}, "
            f"base={self._base:.3f}%, σ={self._noise_std:.4f}, "
            f"profile={self._profile.value})"
        )


# ─── Simulador completo do EPI ────────────────────────────────────────────────
class EPISimulator:
    """
    Simula um EPI completo com múltiplos sensores de gás e sensor de temperatura.

    Responsabilidades:
      - Gerenciar um GasSensorSimulator por gás monitorado
      - Simular a temperatura ambiente com inércia térmica
      - Montar e retornar TelemetryPackets prontos para transmissão
      - Suportar cenários realistas dinâmicos (leak, baseline, cyclic, unstable)
    """

    def __init__(
        self,
        device_id: str,
        worker_id: str,
        location_id: str,
        sensor_configs: Optional[dict] = None,
        scenario: Optional[str] = None,
        seed: Optional[int] = None,
    ):
        self.device_id   = device_id
        self.worker_id   = worker_id
        self.location_id = location_id
        self.scenario    = scenario or "custom"
        self._running    = False

        # Inicializa sensores para cada gás configurado
        self._sensors: dict[str, GasSensorSimulator] = {}
        configs = sensor_configs or {}

        for gas_id, defaults in SIMULATION_BASE_CONCENTRATIONS.items():
            cfg = configs.get(gas_id, {})
            self._sensors[gas_id] = GasSensorSimulator(
                gas_id=gas_id,
                base_concentration=cfg.get("base", defaults),
                noise_std=cfg.get("noise_std", SIMULATION_NOISE_STD),
                profile=cfg.get("profile", SignalProfile.CONSTANT),
                ramp_rate=cfg.get("ramp_rate", 0.001),
                sine_amplitude=cfg.get("sine_amplitude", 0.05),
                sine_period_s=cfg.get("sine_period_s", 60.0),
                step_at_sample=cfg.get("step_at_sample", 30),
                step_target=cfg.get("step_target", 0.5),
                inertia_alpha=cfg.get("inertia_alpha", 1.0),
                peak_target=cfg.get("peak_target", 2.5),
                leak_duration_samples=cfg.get("leak_duration_samples", 120),
                leak_start_sample=cfg.get("leak_start_sample", 0),
                vent_period_s=cfg.get("vent_period_s", 75.0),
                drift_theta=cfg.get("drift_theta", 0.08),
                drift_sigma=cfg.get("drift_sigma", 0.003),
                seed=seed,
            )

        self._temp_rng = np.random.default_rng(seed)
        self._temp_current = float(TEMPERATURE_BASE_C)
        self._temp_drift = float(self._temp_rng.uniform(-0.8, 0.8))

        log.info(
            "EPISimulator inicializado: device=%s, worker=%s, location=%s, scenario=%s, gases=%s",
            device_id, worker_id, location_id, self.scenario, list(self._sensors.keys())
        )

    # ------------------------------------------------------------------
    def _simulate_temperature(self) -> float:
        """Retorna temperatura ambiente simulada com inércia térmica e micro-deriva."""
        target = TEMPERATURE_BASE_C + self._temp_drift + self._temp_rng.normal(loc=0.0, scale=TEMPERATURE_NOISE_STD)
        self._temp_current = 0.85 * self._temp_current + 0.15 * target
        return round(float(self._temp_current), 2)

    @classmethod
    def create_scenario(
        cls,
        scenario_type: str,
        device_id: str,
        worker_id: str,
        location_id: str,
        seed: Optional[int] = None,
    ) -> 'EPISimulator':
        """
        Cria um EPISimulator configurado com cenários físicos avançados:
          - 'leak': vazamento não-linear crescente com turbulência, puffs e co-presença de hidrocarbonetos
          - 'baseline': ambiente seguro com flutuações e drift estocástico orgânico (Ornstein-Uhlenbeck)
          - 'cyclic': ambiente de processo industrial com ventilação periódica
          - 'unstable': processo com micro-vazamentos intermitentes de válvulas
          - 'auto': seleção inteligente baseada no device_id e gravidade do local
        """
        rng = np.random.default_rng(seed)
        scen = scenario_type.lower().strip() if scenario_type else "auto"

        if scen == "auto":
            if device_id == "EPI-001":
                scen = "leak"
            elif device_id == "EPI-002":
                scen = "baseline"
            elif "EXTREME" in location_id or "003" in location_id:
                scen = "leak"
            elif "HIGH" in location_id or "001" in location_id:
                scen = "unstable"
            elif "MEDIUM" in location_id or "002" in location_id:
                scen = "cyclic"
            else:
                scen = rng.choice(["baseline", "cyclic", "unstable"])

        configs = {}

        if scen in ("leak", "escalating", "dynamic_leak"):
            # Cenário de emergência: Vazamento dinâmico em CH4 com arraste de C3H8/C4H10 e traços de CO
            configs["CH4"] = {
                "base": float(rng.uniform(0.015, 0.035)),
                "profile": SignalProfile.DYNAMIC_LEAK,
                "peak_target": float(rng.uniform(2.70, 3.20)),
                "leak_duration_samples": int(rng.integers(70, 110)),
                "leak_start_sample": int(rng.integers(5, 15)),
                "inertia_alpha": 0.28,
                "noise_std": 0.008,
            }
            configs["C3H8"] = {
                "base": 0.002,
                "profile": SignalProfile.DYNAMIC_LEAK,
                "peak_target": float(rng.uniform(0.12, 0.22)),
                "leak_duration_samples": 90,
                "inertia_alpha": 0.25,
            }
            configs["C4H10"] = {
                "base": 0.001,
                "profile": SignalProfile.DYNAMIC_LEAK,
                "peak_target": float(rng.uniform(0.05, 0.10)),
                "leak_duration_samples": 95,
                "inertia_alpha": 0.25,
            }
            configs["CO"] = {
                "base": float(rng.uniform(0.008, 0.018)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.002,
                "inertia_alpha": 0.35,
            }
            configs["H2S"] = {
                "base": float(rng.uniform(0.001, 0.003)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.001,
                "inertia_alpha": 0.35,
            }

        elif scen in ("cyclic", "workzone", "venting"):
            # Cenário operacional industrial com ciclos de exaustão e trabalho
            configs["CH4"] = {
                "base": float(rng.uniform(0.02, 0.05)),
                "profile": SignalProfile.CYCLIC_VENTING,
                "peak_target": float(rng.uniform(0.40, 0.65)),
                "vent_period_s": float(rng.uniform(60.0, 90.0)),
                "inertia_alpha": 0.32,
                "noise_std": 0.006,
            }
            configs["C3H8"] = {
                "base": float(rng.uniform(0.01, 0.03)),
                "profile": SignalProfile.CYCLIC_VENTING,
                "peak_target": float(rng.uniform(0.08, 0.15)),
                "vent_period_s": 75.0,
                "inertia_alpha": 0.30,
            }
            configs["CO"] = {
                "base": float(rng.uniform(0.015, 0.03)),
                "profile": SignalProfile.CYCLIC_VENTING,
                "peak_target": 0.08,
                "vent_period_s": 80.0,
                "inertia_alpha": 0.35,
            }
            configs["H2S"] = {
                "base": 0.001,
                "profile": SignalProfile.STOCHASTIC_DRIFT,
            }
            configs["C4H10"] = {
                "base": 0.005,
                "profile": SignalProfile.STOCHASTIC_DRIFT,
            }

        elif scen in ("unstable", "micro_leak", "flange"):
            # Micro-fugas intermitentes em conexões e válvulas sob pressão
            configs["CH4"] = {
                "base": float(rng.uniform(0.20, 0.35)),
                "profile": SignalProfile.INTERMITTENT_BURSTS,
                "inertia_alpha": 0.35,
                "noise_std": 0.012,
            }
            configs["CO"] = {
                "base": float(rng.uniform(0.02, 0.04)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.005,
                "inertia_alpha": 0.35,
            }
            configs["H2S"] = {
                "base": 0.002,
                "profile": SignalProfile.STOCHASTIC_DRIFT,
            }
            configs["C3H8"] = {
                "base": 0.02,
                "profile": SignalProfile.INTERMITTENT_BURSTS,
            }
            configs["C4H10"] = {
                "base": 0.01,
                "profile": SignalProfile.STOCHASTIC_DRIFT,
            }

        else: # "baseline", "safe", "normal"
            # Turno normal e estável: flutuações orgânicas de baixa intensidade, 100% seguro (R ~ 1% - 6%)
            configs["CH4"] = {
                "base": float(rng.uniform(0.012, 0.025)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.002,
                "noise_std": 0.0015,
                "inertia_alpha": 0.30,
            }
            configs["CO"] = {
                "base": float(rng.uniform(0.006, 0.014)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.0012,
                "noise_std": 0.001,
                "inertia_alpha": 0.30,
            }
            configs["H2S"] = {
                "base": float(rng.uniform(0.001, 0.003)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.0006,
                "noise_std": 0.0005,
                "inertia_alpha": 0.30,
            }
            configs["C3H8"] = {
                "base": float(rng.uniform(0.003, 0.008)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.0008,
                "noise_std": 0.0008,
                "inertia_alpha": 0.30,
            }
            configs["C4H10"] = {
                "base": float(rng.uniform(0.002, 0.005)),
                "profile": SignalProfile.STOCHASTIC_DRIFT,
                "drift_sigma": 0.0006,
                "noise_std": 0.0006,
                "inertia_alpha": 0.30,
            }

        sim = cls(
            device_id=device_id,
            worker_id=worker_id,
            location_id=location_id,
            sensor_configs=configs,
            scenario=scen,
            seed=seed,
        )
        return sim

    # ------------------------------------------------------------------
    def generate_packet(self) -> TelemetryPacket:
        """
        Gera um TelemetryPacket com a leitura atual de todos os sensores.

        Returns:
            TelemetryPacket pronto para serialização JSON e transmissão.
        """
        readings = [sensor.next_reading() for sensor in self._sensors.values()]

        return TelemetryPacket(
            packet_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            device_id=self.device_id,
            worker_id=self.worker_id,
            location_id=self.location_id,
            temperature_c=self._simulate_temperature(),
            readings=readings,
        )

    # ------------------------------------------------------------------
    def run(
        self,
        on_packet: Callable[[TelemetryPacket], None],
        max_packets: Optional[int] = None,
    ) -> None:
        """
        Loop principal de amostragem.

        Gera pacotes na taxa SAMPLE_RATE_HZ e chama on_packet() para cada um.
        Pode ser parado chamando stop() de outra thread, ou via max_packets.

        Args:
            on_packet:   callback chamado com cada TelemetryPacket gerado
            max_packets: limite de pacotes (None = infinito)
        """
        self._running  = True
        interval       = 1.0 / SAMPLE_RATE_HZ
        count          = 0

        log.info(
            "EPISimulator iniciado — taxa: %.1f Hz, intervalo: %.2f s",
            SAMPLE_RATE_HZ, interval
        )

        try:
            while self._running:
                packet = self.generate_packet()
                on_packet(packet)
                count += 1

                if max_packets is not None and count >= max_packets:
                    break

                time.sleep(interval)

        except KeyboardInterrupt:
            log.info("EPISimulator interrompido pelo usuário.")
        finally:
            self._running = False
            log.info("EPISimulator encerrado após %d pacotes.", count)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Para o loop de amostragem."""
        self._running = False

    def configure_sensor(self, gas_id: str, **kwargs) -> None:
        """
        Reconfigura um sensor específico em tempo de execução.
        Útil para simular mudanças de cenário (ex: iniciar vazamento).

        Args:
            gas_id: identificador do gás
            **kwargs: parâmetros aceitos por GasSensorSimulator.__init__
        """
        if gas_id not in self._sensors:
            raise KeyError(f"Sensor '{gas_id}' não existe neste EPI.")
        old = self._sensors[gas_id]
        self._sensors[gas_id] = GasSensorSimulator(gas_id=gas_id, **kwargs)
        log.info("Sensor %s reconfigurado.", gas_id)

    def __repr__(self) -> str:
        return (
            f"EPISimulator(device={self.device_id}, "
            f"worker={self.worker_id}, sensors={list(self._sensors.keys())})"
        )


# ─── Demo standalone ──────────────────────────────────────────────────────────
def _demo_print(packet: TelemetryPacket) -> None:
    """Callback de demonstração: imprime o pacote no terminal."""
    ts = packet.timestamp[11:19]  # HH:MM:SS
    readings_str = "  ".join(
        f"{r.gas_id}={r.raw_percent*100:.2f}% ({r.raw_ppm:.0f}ppm)"
        for r in packet.readings
        if r.raw_percent > 0
    ) or "(todos em zero)"
    print(f"[{ts}] {packet.device_id} | T={packet.temperature_c}°C | {readings_str}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    print("=" * 65)
    print(" SafeGas Monitor — Demo do Simulador de EPI (Etapa 2)")
    print("=" * 65)
    print(" Cenário: CH4 com rampa de vazamento + CO constante baixo")
    print(" Ctrl+C para parar\n")

    epi = EPISimulator(
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
        sensor_configs={
            # CH4: começa em 0%, sobe 0.05% por amostra (simula vazamento)
            "CH4": {
                "base": 0.0,
                "noise_std": 0.005,
                "profile": SignalProfile.RAMP_UP,
                "ramp_rate": 0.05,
            },
            # CO: concentração constante baixa (ambiente normal)
            "CO": {
                "base": 0.01,
                "noise_std": 0.002,
                "profile": SignalProfile.CONSTANT,
            },
            # H2S, C3H8, C4H10: em zero (não há vazamento desses)
        },
    )

    epi.run(on_packet=_demo_print, max_packets=20)
    print("\nDemo encerrado.")
