import logging
import json
import time
import threading
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any
import paho.mqtt.client as mqtt

from config.data_contracts import TelemetryPacket

log = logging.getLogger(__name__)

class ClientSession:
    """Mock da sessao TCP antiga para manter compatibilidade com o PipelineHandler."""
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.packets_received = 0
        self.last_packet_at = ""

class CentralCommandServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883, on_packet: Callable = None):
        self.host = host
        self.port = port
        self._on_packet = on_packet or self._default_packet_handler
        self._sessions: Dict[str, ClientSession] = {}
        self._sessions_lock = threading.Lock()
        
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._running = False
        
        self._total_packets = 0

    def start(self):
        log.info(f"Conectando ao Broker MQTT em {self.host}:{self.port}...")
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()
        self._running = True

    def stop(self):
        self._running = False
        self.client.loop_stop()
        self.client.disconnect()
        log.info("Desconectado do MQTT.")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        log.info(f"Conectado ao MQTT broker com status {reason_code}")
        # Assina o topico
        client.subscribe("safegas/telemetry/#")

    def _on_message(self, client, userdata, msg):
        try:
            raw = msg.payload.decode('utf-8')
            packet = TelemetryPacket.from_json(raw)
            
            with self._sessions_lock:
                if packet.device_id not in self._sessions:
                    self._sessions[packet.device_id] = ClientSession(packet.device_id)
                session = self._sessions[packet.device_id]
                session.packets_received += 1
                session.last_packet_at = datetime.now(timezone.utc).isoformat()
                
            self._total_packets += 1
            self._on_packet(packet, session)
            
        except Exception as e:
            log.warning(f"Falha ao processar mensagem MQTT: {e}")

    def _default_packet_handler(self, packet: TelemetryPacket, session: ClientSession):
        print(f"[CENTRAL] Recebido de {packet.device_id} via MQTT")

    @property
    def active_clients(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)
