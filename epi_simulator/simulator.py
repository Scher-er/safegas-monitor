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
    CONSTANT   = "constant"    # concentração fixa (cenário estável)
    RAMP_UP    = "ramp_up"     # vazamento crescente (emergência)
    RAMP_DOWN  = "ramp_down"   # dispersão após evacuação
    SINUSOIDAL = "sinusoidal"  # oscilação periódica (ventilação intermitente)
    STEP       = "step"        # degrau súbito (ruptura instantânea)


# ─── Sensor individual ────────────────────────────────────────────────────────
class GasSensorSimulator:
    """
    Simula um sensor eletroquímico de gás com ruído branco gaussiano.

    Modelo do sinal:
        C(t) = C_base(t) + η(t)

    Onde:
        C_base(t) = concentração "real" definida pelo SignalProfile
        η(t)      = N(0, σ²) — ruído branco gaussiano

    A concentração resultante é limitada a [0, UEL] para realismo físico.
    """

    def __init__(
        self,
        gas_id: str,
        base_concentration: float = 0.0,
        noise_std: float = SIMULATION_NOISE_STD,
        profile: SignalProfile = SignalProfile.CONSTANT,
        ramp_rate: float = 0.001,      # % v/v por amostra (para RAMP_UP/DOWN)
        sine_amplitude: float = 0.05,  # amplitude da senoide (% v/v)
        sine_period_s: float = 60.0,   # período da senoide (segundos)
        step_at_sample: int = 30,      # amostra em que ocorre o degrau (STEP)
        step_target: float = 0.5,      # valor alvo após o degrau (% v/v)
    ):
        """
        Args:
            gas_id:            identificador do gás (ex: 'CH4')
            base_concentration:concentração base inicial (% v/v)
            noise_std:         desvio padrão do ruído gaussiano
            profile:           perfil temporal do sinal base
            ramp_rate:         taxa de crescimento/queda por amostra (RAMP)
            sine_amplitude:    amplitude da oscilação senoidal
            sine_period_s:     período da senoide em segundos
            step_at_sample:    número da amostra em que o degrau ocorre
            step_target:       valor alvo após o degrau
        """
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

        self._sample_count = 0          # contador de amostras geradas
        self._rng = np.random.default_rng()  # gerador NumPy (reproducível se seed)

        log.debug(
            "GasSensorSimulator criado: gas=%s, base=%.3f%%, σ=%.4f, profile=%s",
            gas_id, base_concentration, noise_std, profile.value
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
            # C(t) = base + A * sin(2π * n / período_em_amostras)
            period_samples = self._sine_period * SAMPLE_RATE_HZ
            return self._base + self._sine_amp * np.sin(2 * np.pi * n / period_samples)

        elif self._profile == SignalProfile.STEP:
            return self._step_tgt if n >= self._step_at else self._base

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
        c_raw  = c_base + noise

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
      - Simular a temperatura ambiente
      - Montar e retornar TelemetryPackets prontos para transmissão
      - Executar loop de amostragem na taxa configurada (SAMPLE_RATE_HZ)
    """

    def __init__(
        self,
        device_id: str,
        worker_id: str,
        location_id: str,
        sensor_configs: Optional[dict] = None,
    ):
        """
        Args:
            device_id:      identificador único do EPI (ex: 'EPI-001')
            worker_id:      matrícula do funcionário (ex: 'F-042')
            location_id:    identificador do local de risco (ex: 'LOC-003')
            sensor_configs: dict opcional para customizar sensores.
                            Formato: {gas_id: {base, noise_std, profile, ...}}
                            Se None, usa os defaults de config/settings.py
        """
        self.device_id   = device_id
        self.worker_id   = worker_id
        self.location_id = location_id
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
            )

        self._temp_rng = np.random.default_rng()
        log.info(
            "EPISimulator inicializado: device=%s, worker=%s, location=%s, gases=%s",
            device_id, worker_id, location_id, list(self._sensors.keys())
        )

    # ------------------------------------------------------------------
    def _simulate_temperature(self) -> float:
        """Retorna temperatura ambiente simulada com ruído."""
        noise = self._temp_rng.normal(loc=0.0, scale=TEMPERATURE_NOISE_STD)
        return round(TEMPERATURE_BASE_C + noise, 2)

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
