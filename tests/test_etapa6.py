"""
SafeGas Monitor — Testes da Etapa 6 (Persistência Híbrida)
===========================================================
Testa:
  1. SQLite — DeviceRepository:     CRUD, validação, atualização de status
  2. SQLite — WorkerRepository:     CRUD, ativação/desativação
  3. SQLite — LocationRepository:   CRUD, filtro por risco
  4. SQLite — AssignmentRepository: atribuição EPI↔Funcionário, devolução, view
  5. MongoDB — MongoTelemetryRepository: insert, query, fallback gracioso
  6. Integração PipelineHandler + MongoDB (modo sem banco = gracioso)

Todos os testes SQLite usam ':memory:' — sem arquivos em disco.
Testes MongoDB verificam disponibilidade e pulam graciosamente se offline.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone, timedelta

from config.data_contracts import ProcessedReading, GasReading, IncidentRecord
from database.sql.sqlite_repository import (
    SQLiteRepository,
    DeviceRepository,
    WorkerRepository,
    LocationRepository,
    AssignmentRepository,
    DeviceRecord,
    WorkerRecord,
    LocationRecord,
    AssignmentRecord,
)
from database.nosql.mongo_repository import MongoTelemetryRepository
from central_command.pipeline_handler import PipelineHandler


# ─── Helpers SQLite ───────────────────────────────────────────────────────────

# Schema sem dados de seed (apenas DDL) para testes isolados
_SCHEMA_DDL_ONLY = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY, model TEXT NOT NULL,
    manufacturer TEXT, serial_number TEXT UNIQUE,
    calibration_date TEXT NOT NULL, next_calibration TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE','MAINTENANCE','RETIRED')),
    gas_targets TEXT NOT NULL DEFAULT 'CH4,CO,H2S',
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
    role TEXT NOT NULL, department TEXT NOT NULL,
    phone TEXT, emergency_contact TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    area TEXT NOT NULL, city TEXT,
    risk_level TEXT NOT NULL DEFAULT 'MEDIUM'
        CHECK (risk_level IN ('LOW','MEDIUM','HIGH','EXTREME')),
    gas_hazards TEXT, ventilated INTEGER DEFAULT 0
        CHECK (ventilated IN (0, 1)),
    registered_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id) ON DELETE CASCADE,
    location_id TEXT REFERENCES locations(location_id),
    assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
    returned_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_assignments_device ON assignments(device_id);
CREATE INDEX IF NOT EXISTS idx_assignments_active ON assignments(active);
CREATE VIEW IF NOT EXISTS v_active_assignments AS
SELECT a.assignment_id, a.assigned_at,
       d.device_id, d.model, d.status AS device_status,
       w.worker_id, w.full_name, w.role,
       l.location_id, l.name AS location_name, l.risk_level
FROM assignments a
JOIN devices d ON d.device_id = a.device_id
JOIN workers w ON w.worker_id = a.worker_id
LEFT JOIN locations l ON l.location_id = a.location_id
WHERE a.active = 1;
CREATE VIEW IF NOT EXISTS v_calibration_alerts AS
SELECT device_id, model, calibration_date, next_calibration,
    CASE WHEN date(next_calibration) < date('now') THEN 'VENCIDA'
         WHEN date(next_calibration) < date('now', '+30 day') THEN 'PROXIMA'
         ELSE 'OK' END AS calibration_status
FROM devices WHERE status = 'ACTIVE';
"""


def _make_repo(cls):
    """Cria repositório em memória sem dados de seed."""
    repo = cls.__new__(cls)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_DDL_ONLY)
    conn.commit()
    repo._conn = conn
    repo._db_path = ":memory:"
    return repo


def _device_repo() -> DeviceRepository:
    return _make_repo(DeviceRepository)

def _worker_repo() -> WorkerRepository:
    return _make_repo(WorkerRepository)

def _location_repo() -> LocationRepository:
    return _make_repo(LocationRepository)

def _assignment_repo() -> AssignmentRepository:
    return _make_repo(AssignmentRepository)

def _sample_device(suffix="01") -> DeviceRecord:
    return DeviceRecord(
        device_id=f"EPI-T{suffix}",
        model="SafeGas Mk.I (Test)",
        manufacturer="TestLab",
        serial_number=f"SN-T{suffix}",
        calibration_date="2026-01-01",
        next_calibration="2026-07-01",
        status="ACTIVE",
        gas_targets="CH4,CO,H2S",
    )

def _sample_worker(suffix="01") -> WorkerRecord:
    return WorkerRecord(
        worker_id=f"W-T{suffix}",
        full_name=f"Funcionário Teste {suffix}",
        role="Técnico de Campo",
        department="Manutenção",
        phone="(12)99999-0000",
        active=1,
    )

def _sample_location(suffix="01") -> LocationRecord:
    return LocationRecord(
        location_id=f"LOC-T{suffix}",
        name=f"Local de Teste {suffix}",
        area="Zona Teste",
        city="São José dos Campos",
        risk_level="HIGH",
        gas_hazards="CH4,CO",
        ventilated=0,
    )

def _sample_processed() -> ProcessedReading:
    return ProcessedReading(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id="EPI-MONGO",
        worker_id="W-MONGO",
        location_id="LOC-MONGO",
        temperature_c=27.5,
        readings=[
            GasReading(
                gas_id="CH4",
                raw_ppm=1250.0,
                raw_percent=0.125,
                filtered_percent=0.121,
                lel_contribution=0.024,
            )
        ],
        lel_mix_percent=412.0,
        risk_ratio_percent=2.42,
        alert_level="NORMAL",
        filter_used="kalman",
    )


# ─── Testes DeviceRepository ──────────────────────────────────────────────────

def test_device_register_and_get():
    """Registra e recupera um EPI por ID."""
    repo = _device_repo()
    dev = _sample_device()
    repo.register(dev)
    fetched = repo.get_by_id(dev.device_id)
    assert fetched is not None, "EPI não encontrado após registro"
    assert fetched.device_id == dev.device_id
    assert fetched.model == dev.model
    assert fetched.serial_number == dev.serial_number
    print(f"  [OK] Registro e recuperação: {fetched.device_id}")


def test_device_not_found():
    """get_by_id deve retornar None para ID inexistente."""
    repo = _device_repo()
    result = repo.get_by_id("EPI-INEXISTENTE")
    assert result is None
    print("  [OK] get_by_id retorna None para ID inexistente")


def test_device_update_status():
    """Atualização de status deve persistir."""
    repo = _device_repo()
    dev = _sample_device()
    repo.register(dev)
    updated = repo.update_status(dev.device_id, "MAINTENANCE")
    assert updated
    fetched = repo.get_by_id(dev.device_id)
    assert fetched.status == "MAINTENANCE"
    print(f"  [OK] Status atualizado: ACTIVE → MAINTENANCE")


def test_device_update_nonexistent():
    """Atualizar dispositivo inexistente retorna False."""
    repo = _device_repo()
    result = repo.update_status("EPI-X", "RETIRED")
    assert result is False
    print("  [OK] update_status de ID inexistente retorna False")


def test_device_list_all():
    """list_all retorna todos os EPIs; list_all(status) filtra corretamente."""
    repo = _device_repo()
    repo.register(_sample_device("01"))
    repo.register(_sample_device("02"))
    repo.register(_sample_device("03"))
    repo.update_status("EPI-T03", "MAINTENANCE")

    all_devs = repo.list_all()
    active_devs = repo.list_all(status="ACTIVE")

    assert len(all_devs) == 3
    assert len(active_devs) == 2
    print(f"  [OK] list_all: {len(all_devs)} total, {len(active_devs)} ativos")


def test_device_delete():
    """Delete deve remover o registro."""
    repo = _device_repo()
    dev = _sample_device()
    repo.register(dev)
    deleted = repo.delete(dev.device_id)
    assert deleted
    assert repo.get_by_id(dev.device_id) is None
    print("  [OK] Delete de EPI funcional")


def test_device_duplicate_raises():
    """Inserir device_id duplicado deve lançar exceção."""
    repo = _device_repo()
    dev = _sample_device()
    repo.register(dev)
    try:
        repo.register(dev)
        assert False, "Deveria lançar exceção para device_id duplicado"
    except Exception:
        pass
    print("  [OK] device_id duplicado lança exceção corretamente")


def test_device_calibration_alerts_view():
    """View v_calibration_alerts deve retornar status de calibração."""
    repo = _device_repo()
    dev_ok = DeviceRecord(
        device_id="EPI-CAL-OK",
        model="Test",
        calibration_date="2026-01-01",
        next_calibration="2027-01-01",    # futuro distante → OK
    )
    dev_vencido = DeviceRecord(
        device_id="EPI-CAL-VEN",
        model="Test",
        calibration_date="2025-01-01",
        next_calibration="2025-06-01",    # passado → VENCIDA
    )
    repo.register(dev_ok)
    repo.register(dev_vencido)
    alerts = repo.calibration_alerts()

    statuses = {a["device_id"]: a["calibration_status"] for a in alerts}
    assert statuses.get("EPI-CAL-VEN") == "VENCIDA"
    assert statuses.get("EPI-CAL-OK") == "OK"
    print(f"  [OK] Alertas de calibração: {statuses}")


# ─── Testes WorkerRepository ──────────────────────────────────────────────────

def test_worker_register_and_get():
    """Registra e recupera um funcionário."""
    repo = _worker_repo()
    w = _sample_worker()
    repo.register(w)
    fetched = repo.get_by_id(w.worker_id)
    assert fetched is not None
    assert fetched.full_name == w.full_name
    assert fetched.active == 1
    print(f"  [OK] Funcionário registrado: {fetched.worker_id}")


def test_worker_deactivate():
    """set_active(False) deve marcar o funcionário como inativo."""
    repo = _worker_repo()
    w = _sample_worker()
    repo.register(w)
    repo.set_active(w.worker_id, False)
    fetched = repo.get_by_id(w.worker_id)
    assert fetched.active == 0

    # list_active não deve retornar inativo
    actives = repo.list_active()
    assert not any(a.worker_id == w.worker_id for a in actives)
    print("  [OK] Desativação de funcionário e filtro de ativos")


def test_worker_list_active_vs_all():
    """list_active e list_all devem retornar contagens corretas."""
    repo = _worker_repo()
    for i in range(1, 4):
        repo.register(_sample_worker(f"0{i}"))
    repo.set_active("W-T02", False)

    all_w = repo.list_all()
    active_w = repo.list_active()

    assert len(all_w) == 3
    assert len(active_w) == 2
    print(f"  [OK] Funcionários: {len(all_w)} total, {len(active_w)} ativos")


# ─── Testes LocationRepository ────────────────────────────────────────────────

def test_location_register_and_get():
    """Registra e recupera um local."""
    repo = _location_repo()
    loc = _sample_location()
    repo.register(loc)
    fetched = repo.get_by_id(loc.location_id)
    assert fetched is not None
    assert fetched.risk_level == "HIGH"
    print(f"  [OK] Local registrado: {fetched.location_id} ({fetched.risk_level})")


def test_location_list_by_risk():
    """list_by_risk deve filtrar corretamente."""
    repo = _location_repo()
    # HIGH
    repo.register(_sample_location("01"))
    # MEDIUM
    repo.register(LocationRecord(
        location_id="LOC-M01", name="Local Médio", area="Zona A",
        risk_level="MEDIUM",
    ))
    # EXTREME
    repo.register(LocationRecord(
        location_id="LOC-E01", name="Local Extremo", area="Zona B",
        risk_level="EXTREME",
    ))
    highs = repo.list_by_risk("HIGH")
    extremes = repo.list_by_risk("EXTREME")
    assert len(highs) == 1
    assert len(extremes) == 1
    print(f"  [OK] list_by_risk: HIGH={len(highs)}, EXTREME={len(extremes)}")


# ─── Testes AssignmentRepository ──────────────────────────────────────────────

def test_assignment_full_cycle():
    """Ciclo completo: registrar EPI+Funcionário, atribuir, devolver."""
    # Usa um banco compartilhado para manter FKs
    repo = AssignmentRepository(db_path=":memory:")
    dev_repo = DeviceRepository.__new__(DeviceRepository)
    dev_repo._conn = repo._conn
    wkr_repo = WorkerRepository.__new__(WorkerRepository)
    wkr_repo._conn = repo._conn
    loc_repo = LocationRepository.__new__(LocationRepository)
    loc_repo._conn = repo._conn

    dev_repo.register(_sample_device())
    wkr_repo.register(_sample_worker())
    loc_repo.register(_sample_location())

    # Atribui
    assignment = AssignmentRecord(
        device_id="EPI-T01",
        worker_id="W-T01",
        location_id="LOC-T01",
    )
    aid = repo.assign(assignment)
    assert aid is not None and aid > 0

    # Verifica atribuição ativa
    active = repo.active_assignments()
    assert len(active) == 1
    assert active[0]["device_id"] == "EPI-T01"
    assert active[0]["worker_id"] == "W-T01"

    # Devolução
    returned = repo.return_device(aid)
    assert returned

    # Sem atribuições ativas após devolução
    active_after = repo.active_assignments()
    assert len(active_after) == 0

    print("  [OK] Ciclo completo: atribuição → uso → devolução")


def test_assignment_get_by_device():
    """get_by_device retorna a atribuição ativa de um EPI."""
    repo = AssignmentRepository(db_path=":memory:")
    # Insere via SQL direto (sem FK em :memory: com tabelas isoladas)
    repo._conn.execute(
        """INSERT INTO devices (device_id, model, calibration_date,
           next_calibration) VALUES ('EPI-GBD', 'M', '2026-01-01', '2026-07-01')"""
    )
    repo._conn.execute(
        """INSERT INTO workers (worker_id, full_name, role, department)
           VALUES ('W-GBD', 'Test User', 'Tech', 'Maint')"""
    )
    repo._conn.commit()
    repo.assign(AssignmentRecord(device_id="EPI-GBD", worker_id="W-GBD"))

    result = repo.get_by_device("EPI-GBD")
    assert result is not None
    assert result["device_id"] == "EPI-GBD"
    assert result["worker_id"] == "W-GBD"
    print("  [OK] get_by_device retorna atribuição ativa correta")


# ─── Testes MongoDB ───────────────────────────────────────────────────────────

def _check_mongo_available() -> bool:
    """Verifica se MongoDB está acessível (timeout 1s)."""
    try:
        repo = MongoTelemetryRepository(server_selection_timeout_ms=1000)
        return repo.is_available
    except Exception:
        return False


def test_mongo_graceful_degradation():
    """Repositório MongoDB em modo degradado (offline) não deve lançar exceção."""
    # Usa URI inválida para forçar modo offline
    repo = MongoTelemetryRepository(
        uri="mongodb://localhost:1/",     # porta inexistente
        server_selection_timeout_ms=200,  # timeout curto
    )
    assert not repo.is_available

    # Todas as operações devem ser no-op
    assert repo.insert_reading(_sample_processed()) is None
    assert repo.get_recent_by_device("EPI-X") == []
    assert repo.get_critical_events() == []
    assert repo.count_by_alert_level() == {}
    print("  [OK] Modo degradado: todas as operações são no-op sem lançar exceção")


def test_mongo_insert_and_query():
    """Se MongoDB disponível: insert + get_recent devem funcionar."""
    if not _check_mongo_available():
        print("  [PULADO] MongoDB offline — teste de inserção pulado")
        return

    repo = MongoTelemetryRepository(
        db_name="safegas_test",
        server_selection_timeout_ms=2000,
    )

    p = _sample_processed()
    mongo_id = repo.insert_reading(p)
    assert mongo_id is not None, "insert_reading retornou None com MongoDB disponível"

    recent = repo.get_recent_by_device(p.device_id, limit=5)
    assert len(recent) >= 1
    found = any(r["packet_id"] == p.packet_id for r in recent)
    assert found, "Pacote inserido não encontrado na query"

    # Limpa dado de teste
    repo._telemetry.delete_one({"packet_id": p.packet_id})
    repo.close()
    print(f"  [OK] MongoDB insert+query: _id={mongo_id[:12]}...")


def test_mongo_insert_incident():
    """Se MongoDB disponível: inserção de incidente funciona."""
    if not _check_mongo_available():
        print("  [PULADO] MongoDB offline — teste de incidente pulado")
        return

    repo = MongoTelemetryRepository(
        db_name="safegas_test",
        server_selection_timeout_ms=2000,
    )
    incident = IncidentRecord(
        incident_id=str(uuid.uuid4()),
        triggered_at=datetime.now(timezone.utc).isoformat(),
        device_id="EPI-INC",
        worker_id="W-INC",
        location_id="LOC-INC",
        peak_risk_ratio=87.5,
        latex_report_path="reports/test.tex",
    )
    mongo_id = repo.insert_incident(incident)
    assert mongo_id is not None

    incidents = repo.get_incidents_by_device("EPI-INC", limit=5)
    assert any(i["incident_id"] == incident.incident_id for i in incidents)

    # Limpa dado de teste
    repo._incidents.delete_one({"incident_id": incident.incident_id})
    repo.close()
    print(f"  [OK] MongoDB incidente inserido: _id={mongo_id[:12]}...")


# ─── PipelineHandler com MongoDB desativado ───────────────────────────────────

def test_pipeline_handler_without_mongo():
    """PipelineHandler com enable_mongo=False deve funcionar normalmente."""
    import uuid
    from config.data_contracts import TelemetryPacket, GasReading

    handler = PipelineHandler(filter_mode="kalman", verbose_output=False,
                               enable_mongo=False)
    pkt = TelemetryPacket(
        packet_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        device_id="EPI-NOMONGO",
        worker_id="W-NM",
        location_id="LOC-NM",
        temperature_c=25.0,
        readings=[GasReading(gas_id="CH4", raw_ppm=500.0, raw_percent=0.05)],
    )
    result = handler(pkt)
    assert result is not None
    assert result.alert_level in ["NORMAL", "ATTENTION", "WARNING", "CRITICAL"]
    assert handler.stats["mongo_available"] is False
    print(f"  [OK] PipelineHandler sem MongoDB: level={result.alert_level}, mongo=False")


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_all():
    print("\n" + "=" * 65)
    print("  SafeGas Monitor — Testes da Etapa 6 (Persistência Híbrida)")
    print("=" * 65)

    groups = [
        ("DeviceRepository (SQLite)", [
            test_device_register_and_get,
            test_device_not_found,
            test_device_update_status,
            test_device_update_nonexistent,
            test_device_list_all,
            test_device_delete,
            test_device_duplicate_raises,
            test_device_calibration_alerts_view,
        ]),
        ("WorkerRepository (SQLite)", [
            test_worker_register_and_get,
            test_worker_deactivate,
            test_worker_list_active_vs_all,
        ]),
        ("LocationRepository (SQLite)", [
            test_location_register_and_get,
            test_location_list_by_risk,
        ]),
        ("AssignmentRepository (SQLite)", [
            test_assignment_full_cycle,
            test_assignment_get_by_device,
        ]),
        ("MongoTelemetryRepository", [
            test_mongo_graceful_degradation,
            test_mongo_insert_and_query,
            test_mongo_insert_incident,
        ]),
        ("PipelineHandler + Persistência", [
            test_pipeline_handler_without_mongo,
        ]),
    ]

    total_passed, total_tests = 0, 0
    for group_name, tests in groups:
        print(f"\n-- {group_name} " + "-" * max(1, 52 - len(group_name)))
        for t in tests:
            total_tests += 1
            try:
                print(f"\n[TESTE] {t.__name__}")
                t()
                total_passed += 1
            except Exception as e:
                print(f"  [FALHOU] {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'=' * 65}")
    print(f"  Resultado: {total_passed}/{total_tests} testes passaram")
    print("=" * 65 + "\n")
    return total_passed == total_tests


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    success = run_all()
    sys.exit(0 if success else 1)
