"""
SafeGas Monitor — Servidor da Central de Comando — Etapa 3
===========================================================
Responsabilidades:
  - Aceitar múltiplos clientes EPI via TCP (uma thread por cliente)
  - Receber e desserializar TelemetryPackets (protocolo length-prefixed)
  - Encaminhar cada pacote para o pipeline de processamento
  - Tratar desconexões e reconexões de forma robusta

Pipeline de processamento (preenchido nas etapas seguintes):
    _handle_packet(packet)
        → [Etapa 4] filtrar_sinal()
        → [Etapa 5] calcular_lel()
        → [Etapa 6] persistir()
        → [Etapa 7] gerar_laudo()  ← somente se CRÍTICO

Uso standalone:
    python -m central_command.server
    python main.py server

Referências:
  - Modelo threading por cliente: Stevens, "Unix Network Programming", cap. 4
"""

import sys
import os
import socket
import threading
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import SOCKET_HOST, SOCKET_PORT, SOCKET_TIMEOUT_S
from config.data_contracts import TelemetryPacket
from epi_simulator.client import recv_message   # reutiliza utilitário de framing

log = logging.getLogger(__name__)


# ─── Informações de uma conexão ativa ─────────────────────────────────────────

class ClientSession:
    """Representa uma sessão ativa de um EPI conectado."""

    def __init__(self, conn: socket.socket, addr: tuple):
        self.conn = conn
        self.addr = addr
        self.device_id: Optional[str] = None   # preenchido no 1º pacote
        self.connected_at = datetime.now(timezone.utc).isoformat()
        self.packets_received = 0
        self.last_packet_at: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"ClientSession(addr={self.addr}, device={self.device_id}, "
            f"pkts={self.packets_received})"
        )


# ─── Servidor TCP ─────────────────────────────────────────────────────────────

class CentralCommandServer:
    """
    Servidor TCP multithreaded da Central de Comando.

    Aceita N conexões simultâneas de EPIs, recebe TelemetryPackets
    via protocolo length-prefixed e os encaminha para o pipeline.

    Uso como context manager:
        with CentralCommandServer() as srv:
            srv.wait()   # bloqueia até Ctrl+C

    Uso com callback personalizado:
        srv = CentralCommandServer(on_packet=meu_processador)
        srv.start()
    """

    def __init__(
        self,
        host: str = SOCKET_HOST,
        port: int = SOCKET_PORT,
        on_packet: Optional[Callable[[TelemetryPacket, ClientSession], None]] = None,
        on_client_connect: Optional[Callable[[ClientSession], None]] = None,
        on_client_disconnect: Optional[Callable[[ClientSession], None]] = None,
        socket_timeout: float = SOCKET_TIMEOUT_S,
    ):
        """
        Args:
            host:                 endereço para bind
            port:                 porta TCP
            on_packet:            callback chamado para cada pacote recebido.
                                  Assinatura: fn(packet, session)
                                  Se None, usa _default_packet_handler.
            on_client_connect:    callback ao aceitar nova conexão
            on_client_disconnect: callback ao detectar desconexão
            socket_timeout:       timeout em segundos para operações de socket
        """
        self.host = host
        self.port = port
        self.socket_timeout = socket_timeout

        self._on_packet = on_packet or self._default_packet_handler
        self._on_client_connect = on_client_connect
        self._on_client_disconnect = on_client_disconnect

        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._sessions: Dict[str, ClientSession] = {}  # addr_str → session
        self._sessions_lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None

        # Estatísticas globais
        self._total_packets = 0
        self._total_clients = 0
        self._start_time: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_clients(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    @property
    def stats(self) -> dict:
        return {
            "running": self._running,
            "start_time": self._start_time,
            "total_packets_received": self._total_packets,
            "total_clients_served": self._total_clients,
            "active_clients": self.active_clients,
        }

    # ------------------------------------------------------------------
    def start(self) -> None:
        """
        Inicia o servidor em uma thread dedicada de aceitação.
        Não bloqueia — retorna imediatamente após bind.
        """
        if self._running:
            log.warning("Servidor já está rodando.")
            return

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(10)   # fila de backlog de até 10 conexões pendentes
        self._running = True
        self._start_time = datetime.now(timezone.utc).isoformat()

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="CentralAccept",
            daemon=True,
        )
        self._accept_thread.start()

        log.info("Central de Comando escutando em %s:%d", self.host, self.port)
        print(f"[CENTRAL] Servidor iniciado em {self.host}:{self.port}")

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Para o servidor e encerra todas as sessões ativas."""
        if not self._running:
            return

        log.info("Encerrando Central de Comando...")
        self._running = False

        # Fecha o socket do servidor para desbloquear o accept()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass

        # Encerra todas as sessões ativas
        with self._sessions_lock:
            for session in list(self._sessions.values()):
                try:
                    session.conn.close()
                except OSError:
                    pass
            self._sessions.clear()

        if self._accept_thread:
            self._accept_thread.join(timeout=3.0)

        log.info(
            "Central encerrada. Total: %d pacotes de %d clientes.",
            self._total_packets, self._total_clients,
        )
        print(f"[CENTRAL] Encerrado — {self._total_packets} pacotes processados.")

    # ------------------------------------------------------------------
    def wait(self) -> None:
        """Bloqueia até o servidor ser parado (via stop() ou Ctrl+C)."""
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[CENTRAL] Interrompido pelo usuário.")
        finally:
            self.stop()

    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        """Thread que aceita novas conexões TCP continuamente."""
        self._server_sock.settimeout(1.0)   # timeout para poder checar _running
        while self._running:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue    # re-checa _running
            except OSError:
                break       # servidor foi fechado

            session = ClientSession(conn, addr)
            addr_str = f"{addr[0]}:{addr[1]}"

            with self._sessions_lock:
                self._sessions[addr_str] = session
                self._total_clients += 1

            log.info("Nova conexão de %s (total ativo: %d)", addr_str, self.active_clients)

            if self._on_client_connect:
                self._on_client_connect(session)

            # Uma thread por cliente
            t = threading.Thread(
                target=self._client_loop,
                args=(session, addr_str),
                name=f"EPI-{addr_str}",
                daemon=True,
            )
            t.start()

    # ------------------------------------------------------------------
    def _client_loop(self, session: ClientSession, addr_str: str) -> None:
        """
        Thread dedicada a um EPI conectado.
        Lê pacotes em loop até a conexão ser encerrada.
        """
        try:
            session.conn.settimeout(self.socket_timeout * 2)  # timeout generoso por leitura
        except OSError:
            return  # socket já foi fechado antes de chegarmos aqui

        try:
            while self._running:
                raw = recv_message(session.conn)
                if raw is None:
                    log.info("EPI %s desconectou normalmente.", addr_str)
                    break

                try:
                    packet = TelemetryPacket.from_json(raw)
                except (KeyError, TypeError, ValueError) as e:
                    log.warning("Pacote malformado de %s: %s", addr_str, e)
                    continue

                # Atualiza metadados da sessão
                session.device_id = packet.device_id
                session.packets_received += 1
                session.last_packet_at = datetime.now(timezone.utc).isoformat()
                self._total_packets += 1

                # Encaminha ao pipeline
                try:
                    self._on_packet(packet, session)
                except Exception as e:
                    log.error("Erro no pipeline para pacote %s: %s", packet.packet_id[:8], e)

        except (ConnectionResetError, OSError) as e:
            log.warning("Conexão com %s perdida: %s", addr_str, e)
        finally:
            # Limpa a sessão
            try:
                session.conn.close()
            except OSError:
                pass
            with self._sessions_lock:
                self._sessions.pop(addr_str, None)

            if self._on_client_disconnect:
                self._on_client_disconnect(session)

            log.info(
                "Sessão %s encerrada — %d pacotes recebidos.",
                addr_str, session.packets_received,
            )

    # ------------------------------------------------------------------
    def _default_packet_handler(
        self, packet: TelemetryPacket, session: ClientSession
    ) -> None:
        """
        Handler padrão: exibe o pacote no terminal de forma legível.
        Será substituído por handlers reais nas Etapas 4-7.
        """
        ts = packet.timestamp[11:19]
        gases = ", ".join(
            f"{r.gas_id}={r.raw_percent*100:.3f}%"
            for r in packet.readings
            if r.raw_percent > 0
        ) or "todos zerados"
        print(
            f"[CENTRAL] [{ts}] {packet.device_id} | "
            f"T={packet.temperature_c:.1f}°C | {gases} | "
            f"pkt#{session.packets_received}"
        )

    # ------------------------------------------------------------------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def __repr__(self) -> str:
        status = "rodando" if self._running else "parado"
        return (
            f"CentralCommandServer({self.host}:{self.port}, "
            f"{status}, clientes={self.active_clients})"
        )


# ─── Demo standalone ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    print("=" * 60)
    print(" SafeGas Monitor — Central de Comando (Etapa 3)")
    print(" Aguardando conexões de EPIs em 127.0.0.1:9000...")
    print(" Ctrl+C para encerrar\n")

    with CentralCommandServer() as server:
        server.wait()
