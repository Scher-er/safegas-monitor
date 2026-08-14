"""
SafeGas Monitor — Cliente Socket TCP (EPI → Central) — Etapa 3
===============================================================
Responsabilidades:
  - Conectar ao servidor (Central de Comando) via TCP
  - Enviar TelemetryPackets serializados em JSON com framing de 4 bytes
  - Reconectar automaticamente em caso de falha de rede
  - Integrar com EPISimulator (Etapa 2) para pipeline completo

Protocolo de framing (length-prefixed):
  ┌──────────────────────────┬──────────────────────────┐
  │  4 bytes (uint32 BE)     │  N bytes (JSON UTF-8)    │
  │  tamanho do payload N    │  TelemetryPacket JSON     │
  └──────────────────────────┴──────────────────────────┘

Uso standalone:
    python -m epi_simulator.client

Referências:
  - Framing: Stevens, "Unix Network Programming", Vol. 1, cap. 3
"""

import sys
import os
import socket
import struct
import time
import logging
import threading
from typing import Optional, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import (
    SOCKET_HOST,
    SOCKET_PORT,
    SOCKET_TIMEOUT_S,
    RECONNECT_INTERVAL_S,
    SAMPLE_RATE_HZ,
)
from config.data_contracts import TelemetryPacket
from epi_simulator.simulator import EPISimulator, SignalProfile

log = logging.getLogger(__name__)

# Formato do header de framing: unsigned int 32 bits big-endian
_FRAME_HEADER = struct.Struct("!I")   # "!" = network (big-endian), "I" = uint32


# ─── Utilitários de protocolo ─────────────────────────────────────────────────

def encode_message(payload: str) -> bytes:
    """
    Empacota uma string JSON no protocolo length-prefixed.

    Args:
        payload: string JSON do TelemetryPacket

    Returns:
        bytes prontos para envio via socket (header 4B + payload UTF-8)
    """
    data = payload.encode("utf-8")
    header = _FRAME_HEADER.pack(len(data))
    return header + data


def recv_message(sock: socket.socket) -> Optional[str]:
    """
    Recebe uma mensagem completa do socket usando framing.
    Lê exatamente 4 bytes de header, depois N bytes de payload.

    Args:
        sock: socket TCP já conectado

    Returns:
        String JSON recebida, ou None se a conexão foi encerrada.

    Raises:
        ConnectionError: em caso de erro de rede inesperado
    """
    # Lê header (4 bytes exatos)
    raw_header = _recv_exact(sock, _FRAME_HEADER.size)
    if raw_header is None:
        return None  # conexão encerrada normalmente

    payload_len = _FRAME_HEADER.unpack(raw_header)[0]

    if payload_len == 0 or payload_len > 10_000_000:  # sanidade: máx 10 MB
        raise ConnectionError(f"Tamanho de payload inválido: {payload_len}")

    # Lê payload (N bytes exatos)
    raw_payload = _recv_exact(sock, payload_len)
    if raw_payload is None:
        return None

    return raw_payload.decode("utf-8")


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    """
    Lê exatamente n bytes do socket, bloqueando até completar.
    Retorna None se a conexão for encerrada antes de completar.
    """
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (ConnectionResetError, OSError):
            return None
        if not chunk:          # peer fechou a conexão
            return None
        buf.extend(chunk)
    return bytes(buf)


# ─── Cliente TCP ──────────────────────────────────────────────────────────────

class EPISocketClient:
    """
    Cliente TCP que transmite TelemetryPackets para a Central de Comando.

    Features:
      - Framing length-prefixed (4 bytes big-endian)
      - Reconexão automática com backoff configurável
      - Thread-safe: pode ser usado de qualquer thread
      - Callback on_connect/on_disconnect para monitoramento externo
    """

    def __init__(
        self,
        host: str = SOCKET_HOST,
        port: int = SOCKET_PORT,
        timeout: float = SOCKET_TIMEOUT_S,
        reconnect_interval: float = RECONNECT_INTERVAL_S,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
    ):
        """
        Args:
            host:               endereço IP/hostname do servidor
            port:               porta TCP
            timeout:            timeout de operações de socket (segundos)
            reconnect_interval: intervalo entre tentativas de reconexão
            on_connect:         callback chamado ao conectar com sucesso
            on_disconnect:      callback chamado ao perder conexão
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._connected = False
        self._packets_sent = 0
        self._packets_failed = 0

    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        return {
            "packets_sent": self._packets_sent,
            "packets_failed": self._packets_failed,
            "connected": self._connected,
        }

    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """
        Tenta estabelecer conexão TCP com o servidor.

        Returns:
            True se conectado com sucesso, False caso contrário.
        """
        with self._lock:
            if self._connected:
                return True

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
                self._sock = sock
                self._connected = True
                log.info("EPI conectado à Central em %s:%d", self.host, self.port)
                if self.on_connect:
                    self.on_connect()
                return True

            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                log.warning("Falha ao conectar em %s:%d — %s", self.host, self.port, e)
                self._sock = None
                self._connected = False
                return False

    # ------------------------------------------------------------------
    def disconnect(self) -> None:
        """Encerra a conexão de forma limpa."""
        with self._lock:
            self._connected = False
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            log.info(
                "EPI desconectado. Estatísticas: %d enviados, %d falhas.",
                self._packets_sent, self._packets_failed,
            )
            if self.on_disconnect:
                self.on_disconnect()

    # ------------------------------------------------------------------
    def send_packet(self, packet: TelemetryPacket) -> bool:
        """
        Serializa e envia um TelemetryPacket para a Central.

        Se a conexão estiver caída, tenta reconectar antes de enviar.

        Args:
            packet: TelemetryPacket a ser transmitido

        Returns:
            True se enviado com sucesso, False caso contrário.
        """
        if not self._connected:
            log.debug("Sem conexão — tentando reconectar antes de enviar...")
            if not self.connect():
                self._packets_failed += 1
                return False

        try:
            raw = encode_message(packet.to_json())
            with self._lock:
                if self._sock is None:
                    raise OSError("Socket não disponível")
                self._sock.sendall(raw)
            self._packets_sent += 1
            log.debug(
                "Pacote enviado: id=%s, %d bytes, gas=%d",
                packet.packet_id[:8], len(raw), len(packet.readings),
            )
            return True

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            log.warning("Erro ao enviar pacote: %s — reconectando...", e)
            self._connected = False
            self._sock = None
            self._packets_failed += 1
            if self.on_disconnect:
                self.on_disconnect()
            return False

    # ------------------------------------------------------------------
    def connect_with_retry(self, max_attempts: int = 0) -> bool:
        """
        Tenta conectar repetidamente até conseguir ou atingir max_attempts.

        Args:
            max_attempts: 0 = tentar indefinidamente

        Returns:
            True se conectou, False se esgotou as tentativas.
        """
        attempt = 0
        while True:
            attempt += 1
            log.info("Tentativa de conexão #%d...", attempt)
            if self.connect():
                return True
            if max_attempts and attempt >= max_attempts:
                log.error("Número máximo de tentativas atingido (%d).", max_attempts)
                return False
            log.info("Aguardando %.1fs antes de nova tentativa...", self.reconnect_interval)
            time.sleep(self.reconnect_interval)

    # ------------------------------------------------------------------
    def run_with_simulator(
        self,
        epi: EPISimulator,
        max_packets: Optional[int] = None,
        auto_reconnect: bool = True,
    ) -> None:
        """
        Loop integrado: gera pacotes com o EPISimulator e os transmite.

        Args:
            epi:            instância de EPISimulator (Etapa 2)
            max_packets:    limite de pacotes (None = infinito)
            auto_reconnect: reconectar automaticamente em caso de falha
        """
        log.info(
            "Iniciando loop EPI→Central | device=%s | max=%s",
            epi.device_id, max_packets or "∞",
        )

        def _send(packet: TelemetryPacket):
            success = self.send_packet(packet)
            if not success and auto_reconnect:
                time.sleep(self.reconnect_interval)
                self.connect()

        epi.run(on_packet=_send, max_packets=max_packets)

    # ------------------------------------------------------------------
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    def __repr__(self) -> str:
        status = "conectado" if self._connected else "desconectado"
        return f"EPISocketClient({self.host}:{self.port}, {status})"


# ─── Demo standalone ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 60)
    print(" SafeGas Monitor — EPI Cliente (Etapa 3)")
    print(" Conectando à Central em 127.0.0.1:9000...")
    print(" Ctrl+C para parar\n")

    epi = EPISimulator(
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
        sensor_configs={
            "CH4": {"base": 0.0, "noise_std": 0.01,
                    "profile": SignalProfile.RAMP_UP, "ramp_rate": 0.03},
            "CO":  {"base": 0.05, "noise_std": 0.005,
                    "profile": SignalProfile.CONSTANT},
        },
    )

    client = EPISocketClient(
        on_connect=lambda: print("[EPI] ✓ Conectado à Central!"),
        on_disconnect=lambda: print("[EPI] ✗ Conexão perdida."),
    )

    if client.connect_with_retry(max_attempts=5):
        try:
            client.run_with_simulator(epi)
        finally:
            client.disconnect()
    else:
        print("[EPI] Não foi possível conectar. Certifique-se que a Central está rodando.")
