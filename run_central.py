import sys
import os
import time
import logging
import threading
import subprocess

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/central.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from rich.live import Live

from central_command.server import CentralCommandServer
from central_command.pipeline_handler import PipelineHandler
from ui.tui.state import MonitorState
from ui.tui.layout import TuiBuilder

# Import Flask app
from api.server import app as flask_app, init_api

def run_flask_app():
    # Usando Werkzeug Server embutido para ambiente de dev local. Desativar debug log
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    flask_app.run(host="127.0.0.1", port=8000, use_reloader=False)

def main():
    print("Iniciando SafeGas Monitor - Central de Comando (MQTT + Flask)...")
    
    # 1. Iniciar Broker MQTT no background sem poluir o terminal
    print("Iniciando Broker MQTT Local em background...")
    broker_proc = subprocess.Popen(
        [sys.executable, "mqtt_broker.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2) # Aguarda o broker subir
    
    # 2. Iniciar EPI Simulador no background
    print("Iniciando Simulador de EPI em background...")
    epi_proc = subprocess.Popen(
        [sys.executable, "-m", "epi_simulator.client"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    state = MonitorState()
    
    handler = PipelineHandler(
        filter_mode="kalman",
        verbose_output=False,
        enable_mongo=True,
        monitor_state=state,
    )
    
    # MQTT usa porta 1883 por padrao
    server = CentralCommandServer(
        host="127.0.0.1",
        port=1883,
        on_packet=handler,
    )
    
    # Start MQTT Subscriber
    server.start()
    
    # Inicia a API Web (Flask)
    init_api(state)
    api_thread = threading.Thread(target=run_flask_app, daemon=True)
    api_thread.start()
    
    # Inicia a interface Rich (TUI)
    builder = TuiBuilder(state)
    
    try:
        with Live(builder.build_layout(), refresh_per_second=4, screen=True) as live:
            while True:
                live.update(builder.build_layout())
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDesligando servidores...")
        server.stop()
        
        # Encerra processos filhos de forma limpa
        try:
            broker_proc.terminate()
            epi_proc.terminate()
        except:
            pass
            
        print("Central de Comando encerrada e memÃ³ria liberada.")


if __name__ == "__main__":
    main()
