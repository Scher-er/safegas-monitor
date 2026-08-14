"""
SafeGas Monitor — Ponto de Entrada Principal
=============================================
Uso:
    python main.py server    → Inicia a Central de Comando (servidor TCP)
    python main.py client    → Inicia o EPI simulado (cliente TCP)
    python main.py demo      → Inicia ambos no mesmo processo (desenvolvimento)

Exemplo de demo com vazamento crescente de CH4:
    python main.py demo
"""

import sys
import argparse
import logging
import threading
import time

from config.settings import SOCKET_HOST, SOCKET_PORT, SAMPLE_RATE_HZ
from central_command.server import CentralCommandServer
from epi_simulator.simulator import EPISimulator, SignalProfile
from epi_simulator.client import EPISocketClient


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ─── Modo servidor ────────────────────────────────────────────────────────────

def run_server(verbose: bool = False) -> None:
    """Inicia somente a Central de Comando e aguarda conexões."""
    _setup_logging(verbose)
    print("=" * 60)
    print(" SafeGas Monitor — Central de Comando")
    print(f" Escutando em {SOCKET_HOST}:{SOCKET_PORT}")
    print(" Ctrl+C para encerrar\n")
    with CentralCommandServer(host=SOCKET_HOST, port=SOCKET_PORT) as server:
        server.wait()


# ─── Modo cliente ─────────────────────────────────────────────────────────────

def run_client(verbose: bool = False) -> None:
    """Inicia somente o EPI simulado e conecta à Central."""
    _setup_logging(verbose)
    print("=" * 60)
    print(" SafeGas Monitor — EPI Simulado")
    print(f" Conectando à Central em {SOCKET_HOST}:{SOCKET_PORT}")
    print(" Ctrl+C para encerrar\n")

    epi = EPISimulator(
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
        sensor_configs={
            "CH4": {
                "base": 0.0,
                "noise_std": 0.008,
                "profile": SignalProfile.RAMP_UP,
                "ramp_rate": 0.03,       # sobe ~1.8%/min → crítico em ~3 min
            },
            "CO": {
                "base": 0.05,
                "noise_std": 0.003,
                "profile": SignalProfile.CONSTANT,
            },
            "H2S": {
                "base": 0.0,
                "noise_std": 0.001,
                "profile": SignalProfile.CONSTANT,
            },
        },
    )

    client = EPISocketClient(
        host=SOCKET_HOST,
        port=SOCKET_PORT,
        on_connect=lambda: print("[EPI] ✓ Conectado à Central!"),
        on_disconnect=lambda: print("[EPI] ✗ Conexão perdida — reconectando..."),
    )

    if client.connect_with_retry(max_attempts=10):
        try:
            client.run_with_simulator(epi)
        except KeyboardInterrupt:
            print("\n[EPI] Interrompido pelo usuário.")
        finally:
            client.disconnect()
    else:
        print("[EPI] Não foi possível conectar. Certifique-se que a Central está rodando.")


# ─── Modo demo (servidor + cliente no mesmo processo) ─────────────────────────

def run_demo(verbose: bool = False) -> None:
    """
    Inicia servidor e cliente no mesmo processo para desenvolvimento rápido.
    O servidor sobe em thread daemon; o cliente roda na thread principal.
    """
    _setup_logging(verbose)
    print("=" * 60)
    print(" SafeGas Monitor — Modo Demo (EPI + Central)")
    print(" Cenário: vazamento crescente de CH4 + CO constante")
    print(" Ctrl+C para encerrar\n")

    # 1. Sobe o servidor em background
    server = CentralCommandServer(host=SOCKET_HOST, port=SOCKET_PORT)
    server.start()
    time.sleep(0.3)   # garante que o bind/listen completou

    # 2. Cria o EPI simulado com cenário de emergência
    epi = EPISimulator(
        device_id="EPI-DEMO",
        worker_id="F-001",
        location_id="LOC-001",
        sensor_configs={
            "CH4": {
                "base": 0.0,
                "noise_std": 0.008,
                "profile": SignalProfile.RAMP_UP,
                "ramp_rate": 0.05,   # escala rápida para demonstração
            },
            "CO": {
                "base": 0.1,
                "noise_std": 0.005,
                "profile": SignalProfile.SINUSOIDAL,
                "sine_amplitude": 0.02,
                "sine_period_s": 20.0,
            },
        },
    )

    # 3. Cria e conecta o cliente
    client = EPISocketClient(
        host=SOCKET_HOST,
        port=SOCKET_PORT,
        on_connect=lambda: print("[EPI] ✓ Conectado à Central!\n"),
        on_disconnect=lambda: print("[EPI] ✗ Conexão perdida."),
    )

    if not client.connect_with_retry(max_attempts=5):
        print("[DEMO] Falha ao conectar. Encerrando.")
        server.stop()
        return

    # 4. Roda o loop de transmissão
    try:
        client.run_with_simulator(epi)
    except KeyboardInterrupt:
        print("\n[DEMO] Encerrando...")
    finally:
        client.disconnect()
        server.stop()
        stats = server.stats
        print(
            f"\n[DEMO] Sessão encerrada — "
            f"{stats['total_packets_received']} pacotes processados."
        )


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SafeGas Monitor — Sistema de Monitoramento de Gases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py demo           Roda servidor + EPI no mesmo processo
  python main.py server         Roda somente a Central de Comando
  python main.py client         Roda somente o EPI (servidor deve estar ativo)
  python main.py demo -v        Modo demo com logs detalhados
        """,
    )
    parser.add_argument(
        "mode",
        choices=["server", "client", "demo"],
        nargs="?",
        default="demo",
        help="Modo de execução (padrão: demo)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Habilita logs de debug detalhados",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" SafeGas Monitor v0.3.0 (Etapa 3 — Sockets TCP)")
    print(" Projetos em Engenharia da Computação I — UNIVAP 2026")
    print("=" * 60 + "\n")

    if args.mode == "server":
        run_server(args.verbose)
    elif args.mode == "client":
        run_client(args.verbose)
    else:
        run_demo(args.verbose)


if __name__ == "__main__":
    main()
