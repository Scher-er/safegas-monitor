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


# ─── Gerenciador Multi-Dispositivo de Simulação ──────────────────────────────
class SimulationManager:
    """
    Gerenciador multi-dispositivo de simulação de EPIs com publicação MQTT.
    Permite:
      - Executar múltiplos EPIs simultaneamente em uma única conexão MQTT
      - Adicionar e remover EPIs em tempo de execução dinamicamente via API Flask
      - Carregar automaticamente os dispositivos ativos cadastrados no SQLite
      - Configurar cenários diferenciados para cada EPI (leak, baseline, cyclic, unstable)
      - Encerrar de forma limpa sem processos órfãos
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        rate_hz: float = 1.0,
    ):
        self.host = host
        self.port = port
        self.rate_hz = rate_hz
        self._interval = 1.0 / max(0.1, rate_hz)

        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._connected = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # device_id -> EPISimulator
        self._simulators: dict[str, EPISimulator] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_running(self) -> bool:
        return self._running

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        log.info(f"[SimulationManager] Conectado ao broker MQTT ({self.host}:{self.port})")
        self._connected = True

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("[SimulationManager] Desconectado do broker MQTT")
        self._connected = False

    def connect(self) -> bool:
        try:
            self._client.connect(self.host, self.port, 60)
            self._client.loop_start()
            for _ in range(30):
                if self._connected:
                    break
                time.sleep(0.1)
            return True
        except Exception as e:
            log.error(f"[SimulationManager] Falha ao conectar MQTT: {e}")
            return False

    def start(self) -> bool:
        if self._running:
            return True
        if not self._connected:
            self.connect()

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="SimulationManagerThread", daemon=True)
        self._thread.start()
        log.info("[SimulationManager] Thread de simulação iniciada.")
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._connected = False
        log.info("[SimulationManager] Simulação encerrada de forma limpa.")

    def add_device(
        self,
        device_id: str,
        worker_id: Optional[str] = None,
        location_id: Optional[str] = None,
        scenario: str = "auto",
    ) -> EPISimulator:
        with self._lock:
            # Se worker ou location não fornecidos, consulta SQLite
            if not worker_id or not location_id:
                try:
                    from database.sql.sqlite_repository import AssignmentRepository
                    repo = AssignmentRepository()
                    active_ass = repo.active_assignments()
                    repo.close()
                    for ass in active_ass:
                        if ass["device_id"] == device_id:
                            worker_id = worker_id or ass.get("worker_id")
                            location_id = location_id or ass.get("location_id")
                            break
                except Exception as e:
                    log.warning(f"Erro ao buscar atribuição SQLite para {device_id}: {e}")

            worker_id = worker_id or "F-999"
            location_id = location_id or "LOC-001"

            # Gera seed determinístico porém único por dispositivo para garantir comportamentos distintos
            seed = sum(ord(c) for c in device_id) + len(self._simulators) * 37

            sim = EPISimulator.create_scenario(
                scenario_type=scenario,
                device_id=device_id,
                worker_id=worker_id,
                location_id=location_id,
                seed=seed,
            )
            self._simulators[device_id] = sim
            log.info(
                f"[SimulationManager] Dispositivo {device_id} adicionado! Cenário: {sim.scenario} (Worker: {worker_id}, Loc: {location_id})"
            )
            return sim

    def remove_device(self, device_id: str) -> bool:
        with self._lock:
            if device_id in self._simulators:
                del self._simulators[device_id]
                log.info(f"[SimulationManager] Dispositivo {device_id} removido da simulação.")
                return True
            return False

    def list_active(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "device_id": sim.device_id,
                    "worker_id": sim.worker_id,
                    "location_id": sim.location_id,
                    "scenario": getattr(sim, "scenario", "custom"),
                }
                for sim in self._simulators.values()
            ]

    def load_from_sqlite(self) -> int:
        """Carrega os dispositivos ativos com atribuição registrados no SQLite."""
        try:
            from database.sql.sqlite_repository import AssignmentRepository, DeviceRepository
            dev_repo = DeviceRepository()
            all_devices = {d.device_id: d for d in dev_repo.list_all()}
            dev_repo.close()

            assign_repo = AssignmentRepository()
            assignments = assign_repo.active_assignments()
            assign_repo.close()

            count = 0
            seen = set()
            for ass in assignments:
                d_id = ass["device_id"]
                if d_id in seen:
                    continue
                seen.add(d_id)
                dev = all_devices.get(d_id)
                if dev and dev.status != "ACTIVE":
                    continue
                self.add_device(
                    device_id=d_id,
                    worker_id=ass.get("worker_id"),
                    location_id=ass.get("location_id"),
                    scenario="auto",
                )
                count += 1

            if not count:
                # Fallback se não houver atribuições no banco: cria os dois EPIs padrão
                self.add_device("EPI-001", "F-042", "LOC-003", scenario="leak")
                self.add_device("EPI-002", "F-043", "LOC-002", scenario="baseline")
                count = 2

            log.info(f"[SimulationManager] Carregados {count} dispositivos do SQLite para simulação.")
            return count
        except Exception as e:
            log.error(f"[SimulationManager] Erro ao carregar dispositivos do SQLite: {e}")
            self.add_device("EPI-001", "F-042", "LOC-003", scenario="leak")
            self.add_device("EPI-002", "F-043", "LOC-002", scenario="baseline")
            return 2

    def _run_loop(self) -> None:
        log.info("[SimulationManager] Loop de envio de telemetria ativo.")
        while self._running:
            start_time = time.time()
            with self._lock:
                sims = list(self._simulators.values())

            for sim in sims:
                try:
                    packet = sim.generate_packet()
                    topic = f"safegas/telemetry/{packet.device_id}"
                    payload = packet.to_json()
                    self._client.publish(topic, payload)
                except Exception as e:
                    log.error(f"[SimulationManager] Erro ao gerar/publicar pacote de {sim.device_id}: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0.01, self._interval - elapsed)
            time.sleep(sleep_time)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("Iniciando SimulationManager standalone...")
    mgr = SimulationManager()
    mgr.start()
    mgr.load_from_sqlite()
    print(f"Simuladores ativos: {mgr.list_active()}")
    print("Pressione Ctrl+C para encerrar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando SimulationManager...")
    finally:
        mgr.stop()
        print("Finalizado.")
