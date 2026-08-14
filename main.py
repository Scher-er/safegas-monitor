"""
SafeGas Monitor — Ponto de Entrada Principal
=============================================
Uso:
    python main.py server    → Inicia a Central de Comando
    python main.py client    → Inicia o EPI simulado
    python main.py demo      → Inicia ambos localmente (modo demo)
"""

import sys
import argparse


def run_server():
    """Inicia a Central de Comando (servidor)."""
    # TODO (Etapa 3): importar e inicializar CentralCommandServer
    print("[CENTRAL] Servidor não implementado ainda. Ver Etapa 3.")


def run_client():
    """Inicia o EPI simulado (cliente)."""
    # TODO (Etapa 2): importar EPISimulator
    # TODO (Etapa 3): importar EPISocketClient e conectar
    print("[EPI] Cliente não implementado ainda. Ver Etapas 2 e 3.")


def run_demo():
    """Inicia servidor e cliente no mesmo processo (desenvolvimento)."""
    import threading
    print("[DEMO] Modo demonstração - iniciando servidor e cliente...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    import time; time.sleep(1)
    run_client()


def main():
    parser = argparse.ArgumentParser(
        description="SafeGas Monitor — Sistema de Monitoramento de Gases"
    )
    parser.add_argument(
        "mode",
        choices=["server", "client", "demo"],
        nargs="?",
        default="demo",
        help="Modo de execução (padrão: demo)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" SafeGas Monitor v0.1.0 (Etapa 1 — Arquitetura)")
    print(" Disciplina: Projetos em Engenharia da Computação I")
    print(" UNIVAP — 2026")
    print("=" * 60)

    if args.mode == "server":
        run_server()
    elif args.mode == "client":
        run_client()
    else:
        run_demo()


if __name__ == "__main__":
    main()
