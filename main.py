"""
Ponto de entrada CLI para execução modular da Central de Comando ou do Simulador via MQTT.
Para iniciar o ambiente completo integrado (Broker + Central + Simulador + Web + TUI), utilize `run_central.py`.
"""

import argparse
import logging
import time

from config.settings import MQTT_HOST, MQTT_PORT
from central_command.server import CentralCommandServer
from central_command.pipeline_handler import PipelineHandler
from epi_simulator.simulator import EPISimulator, SignalProfile
from epi_simulator.client import EPISocketClient


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_server(verbose: bool = False) -> None:
    """Inicia a Central de Comando subscrita ao broker MQTT."""
    _setup_logging(verbose)
    print("SafeGas Monitor - Central de Comando")
    print(f"Broker MQTT: {MQTT_HOST}:{MQTT_PORT}")
    print("Pipeline ativo: Kalman -> LEL (Le Chatelier) -> Alertas")
    print("Pressione Ctrl+C para encerrar.\n")

    handler = PipelineHandler(filter_mode="kalman", verbose_output=True)
    server = CentralCommandServer(host=MQTT_HOST, port=MQTT_PORT, on_packet=handler)
    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nEncerrando Central de Comando...")
    finally:
        server.stop()


def run_client(verbose: bool = False) -> None:
    """Inicia uma instância de EPI simulado publicando no broker MQTT."""
    _setup_logging(verbose)
    print("SafeGas Monitor - Simulador de EPI")
    print(f"Publicando no broker MQTT em {MQTT_HOST}:{MQTT_PORT}")
    print("Pressione Ctrl+C para encerrar.\n")

    epi = EPISimulator.create_scenario(
        scenario_type="leak",
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
    )

    client = EPISocketClient(
        host=MQTT_HOST,
        port=MQTT_PORT,
        on_connect=lambda: print("[EPI] Conectado ao broker MQTT."),
        on_disconnect=lambda: print("[EPI] Desconectado do broker MQTT."),
    )

    if client.connect_with_retry(max_attempts=10):
        try:
            client.run_with_simulator(epi)
        except KeyboardInterrupt:
            print("\n[EPI] Simulação interrompida pelo usuário.")
        finally:
            client.disconnect()
    else:
        print("[EPI] Falha ao conectar ao broker MQTT.")


def run_demo(verbose: bool = False) -> None:
    """Executa subscriber e simulador no mesmo processo (requer broker MQTT ativo)."""
    _setup_logging(verbose)
    print("SafeGas Monitor - Modo Demo (Central + EPI)")
    print("Pressione Ctrl+C para encerrar.\n")

    handler = PipelineHandler(filter_mode="kalman", verbose_output=True)
    server = CentralCommandServer(host=MQTT_HOST, port=MQTT_PORT, on_packet=handler)
    server.start()
    time.sleep(0.3)

    epi = EPISimulator.create_scenario(
        scenario_type="leak",
        device_id="EPI-DEMO",
        worker_id="F-042",
        location_id="LOC-003",
    )

    client = EPISocketClient(
        host=MQTT_HOST,
        port=MQTT_PORT,
        on_connect=lambda: print("[EPI] Conectado ao broker MQTT.\n"),
        on_disconnect=lambda: print("[EPI] Conexão encerrada."),
    )

    if not client.connect_with_retry(max_attempts=5):
        print("[DEMO] Falha ao conectar ao broker MQTT.")
        server.stop()
        return

    try:
        client.run_with_simulator(epi)
    except KeyboardInterrupt:
        print("\n[DEMO] Encerrando...")
    finally:
        client.disconnect()
        server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="SafeGas Monitor - CLI")
    parser.add_argument(
        "mode",
        choices=["server", "client", "demo"],
        nargs="?",
        default="demo",
        help="Modo de operação (padrão: demo)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Habilita logs detalhados",
    )
    args = parser.parse_args()

    if args.mode == "server":
        run_server(args.verbose)
    elif args.mode == "client":
        run_client(args.verbose)
    else:
        run_demo(args.verbose)


if __name__ == "__main__":
    main()
