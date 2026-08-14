# SafeGas Monitor — Camada de Persistência (ESQUELETO — Etapa 6)
# ================================================================

class SQLiteRepository:
    """
    Repositório SQLite para dados cadastrais estruturados.
    
    IMPLEMENTAR NA ETAPA 6:
    
    Tabelas:
    - workers       (id, name, cpf, role, emergency_contact)
    - devices       (id, serial_number, calibration_date, expiry_date)
    - locations     (id, name, address, plant_image_path, expected_gases)
    - allocations   (id, worker_id, device_id, location_id, shift_start, shift_end)
    - emergency_contacts (id, name, role, phone, email)
    """

    def __init__(self, db_path: str):
        raise NotImplementedError("Implementar na Etapa 6")

    def initialize_schema(self):
        """Cria as tabelas se não existirem (CREATE TABLE IF NOT EXISTS)."""
        raise NotImplementedError("Implementar na Etapa 6")

    # --- Workers ---
    def insert_worker(self, worker: dict) -> int:
        raise NotImplementedError("Implementar na Etapa 6")

    def get_worker(self, worker_id: str) -> dict:
        raise NotImplementedError("Implementar na Etapa 6")

    # --- Devices (EPIs) ---
    def insert_device(self, device: dict) -> int:
        raise NotImplementedError("Implementar na Etapa 6")

    def get_device(self, device_id: str) -> dict:
        raise NotImplementedError("Implementar na Etapa 6")

    # --- Locations ---
    def insert_location(self, location: dict) -> int:
        raise NotImplementedError("Implementar na Etapa 6")

    def get_location(self, location_id: str) -> dict:
        raise NotImplementedError("Implementar na Etapa 6")

    # --- Allocations ---
    def create_allocation(self, worker_id: str, device_id: str, location_id: str,
                          shift_start: str, shift_end: str) -> int:
        raise NotImplementedError("Implementar na Etapa 6")

    def get_active_allocation(self, device_id: str) -> dict:
        raise NotImplementedError("Implementar na Etapa 6")


class MongoTelemetryRepository:
    """
    Repositório MongoDB para logs de telemetria de alta frequência.
    
    IMPLEMENTAR NA ETAPA 6:
    
    Coleções:
    - telemetry: uma entrada por leitura (ProcessedReading)
    - incidents:  uma entrada por ocorrência crítica (IncidentRecord)
    
    Índices recomendados:
    - telemetry: {device_id: 1, timestamp: -1}
    - incidents: {triggered_at: -1}
    """

    def __init__(self, uri: str, db_name: str):
        raise NotImplementedError("Implementar na Etapa 6")

    def insert_telemetry(self, processed_reading: dict):
        """Grava uma leitura processada no MongoDB."""
        raise NotImplementedError("Implementar na Etapa 6")

    def get_recent_telemetry(self, device_id: str, minutes: int) -> list:
        """Retorna as últimas `minutes` minutos de telemetria de um EPI."""
        raise NotImplementedError("Implementar na Etapa 6")

    def insert_incident(self, incident: dict):
        raise NotImplementedError("Implementar na Etapa 6")
