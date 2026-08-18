"""
SafeGas Monitor — Central de Comando (App Principal)
====================================================
Inicializa o servidor TCP para escutar os EPIs, o pipeline de
processamento (Filtros → LEL → Alertas → MongoDB → LaTeX) e
renderiza a interface gráfica no terminal (TUI) em tempo real.
"""

import sys
import os
import time
import logging
import threading

# Configura o logger para ignorar stdout e gravar apenas em arquivo,
# evitando que os logs "sujem" a interface do Rich.
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/central.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

import uvicorn
from rich.live import Live

from config.settings import SOCKET_HOST, SOCKET_PORT
from central_command.server import CentralCommandServer
from central_command.pipeline_handler import PipelineHandler
from ui.tui.state import MonitorState
from ui.tui.layout import TuiBuilder
from api.server import app as fast_app, init_api


def main():
    print("Iniciando SafeGas Monitor - Central de Comando...")
    
    # 1. Cria o estado compartilhado da TUI
    state = MonitorState()
    
    # 2. Inicializa o Pipeline (Etapas 4-7) acoplado ao estado
    # verbose=False para não conflitar com a TUI no terminal
    handler = PipelineHandler(
        filter_mode="kalman",
        verbose_output=False,
        enable_mongo=True,
        monitor_state=state,
    )
    
    # 3. Inicializa o servidor TCP (Etapa 3)
    server = CentralCommandServer(
        host=SOCKET_HOST,
        port=SOCKET_PORT,
        on_packet=handler,
    )
    
    # 4. Inicia o servidor em uma thread separada (daemon)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    
    # 5. Inicializa a API Web (Etapa 9)
    init_api(state)
    def run_uvicorn():
        # Desativa os logs do uvicorn para não poluir o TUI
        uvicorn.run(fast_app, host="127.0.0.1", port=8000, log_level="critical")
        
    api_thread = threading.Thread(target=run_uvicorn, daemon=True)
    api_thread.start()
    
    # 6. Inicia a interface Rich (TUI) na thread principal
    builder = TuiBuilder(state)
    
    try:
        # refresh_per_second=4 oferece uma boa responsividade sem consumir muita CPU
        with Live(builder.build_layout(), refresh_per_second=4, screen=True) as live:
            while True:
                # Atualiza o layout a cada frame
                live.update(builder.build_layout())
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDesligando servidores...")
        server.stop()
        server_thread.join(timeout=2.0)
        print("Central de Comando encerrada.")


if __name__ == "__main__":
    main()
