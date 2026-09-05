import time
import logging
import threading
from typing import Callable, Optional
import paho.mqtt.client as mqtt

from config.data_contracts import TelemetryPacket
from epi_simulator.simulator import EPISimulator, SignalProfile

log = logging.getLogger(__name__)

class EPISocketClient:
    """Mock mantido com mesmo nome do TCP, mas usando MQTT para minimizar impacto estrutural."""
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        timeout: float = 5.0,
        reconnect_interval: float = 2.0,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._mqtt_on_connect
        self.client.on_disconnect = self._mqtt_on_disconnect
        
        self._connected = False
        self._packets_sent = 0
        self._packets_failed = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _mqtt_on_connect(self, client, userdata, flags, reason_code, properties):
        log.info(f"Conectado ao MQTT Broker com codigo: {reason_code}")
        self._connected = True
        if self.on_connect:
            self.on_connect()

    def _mqtt_on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("Desconectado do MQTT Broker.")
        self._connected = False
        if self.on_disconnect:
            self.on_disconnect()

    def connect(self) -> bool:
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            log.error(f"Falha ao conectar no broker MQTT: {e}")
            return False

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def send_packet(self, packet: TelemetryPacket) -> bool:
        if not self._connected:
            return False
            
        try:
            topic = f"safegas/telemetry/{packet.device_id}"
            payload = packet.to_json()
            self.client.publish(topic, payload)
            self._packets_sent += 1
            return True
        except Exception as e:
            self._packets_failed += 1
            return False

    def connect_with_retry(self, max_attempts: int = 0) -> bool:
        return self.connect()

    def run_with_simulator(
        self,
        epi: EPISimulator,
        max_packets: Optional[int] = None,
        auto_reconnect: bool = True,
    ) -> None:
        log.info(f"Iniciando loop EPI->MQTT | device={epi.device_id}")

        def _send(packet: TelemetryPacket):
            self.send_packet(packet)

        epi.run(on_packet=_send, max_packets=max_packets)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    epi = EPISimulator(
        device_id="EPI-001",
        worker_id="F-042",
        location_id="LOC-003",
        sensor_configs={
            "CH4": {"base": 0.0, "noise_std": 0.01, "profile": SignalProfile.RAMP_UP, "ramp_rate": 0.1},
        },
    )

    client = EPISocketClient(
        on_connect=lambda: print("[EPI] Conectado ao Broker!"),
        on_disconnect=lambda: print("[EPI] Conexao perdida."),
    )

    if client.connect_with_retry(max_attempts=5):
        try:
            client.run_with_simulator(epi)
        finally:
            client.disconnect()
