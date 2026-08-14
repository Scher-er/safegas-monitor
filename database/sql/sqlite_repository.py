"""
SafeGas Monitor — Repositório SQLite — Etapa 6
===============================================
Persistência relacional para cadastros institucionais.
Usa o módulo sqlite3 da biblioteca padrão do Python — sem dependências extras.

Repositórios disponíveis:
  - SQLiteRepository (base): conexão, schema, contexto
  - DeviceRepository:   CRUD de EPIs (devices)
  - WorkerRepository:   CRUD de funcionários (workers)
  - LocationRepository: CRUD de locais de risco (locations)
  - AssignmentRepository: atribuição EPI ↔ Funcionário

Modo in-memory (':memory:') disponível para testes unitários.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from typing import Optional

from config.settings import SQLITE_DB_PATH

log = logging.getLogger(__name__)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


# ─── Dataclasses de domínio ───────────────────────────────────────────────────

@dataclass
class DeviceRecord:
    device_id:        str
    model:            str
    calibration_date: str               # ISO 8601 date
    next_calibration: str               # ISO 8601 date
    manufacturer:     Optional[str] = None
    serial_number:    Optional[str] = None
    status:           str = "ACTIVE"
    gas_targets:      str = "CH4,CO,H2S"
    notes:            Optional[str] = None


@dataclass
class WorkerRecord:
    worker_id:         str
    full_name:         str
    role:              str
    department:        str
    phone:             Optional[str] = None
    emergency_contact: Optional[str] = None
    active:            int = 1


@dataclass
class LocationRecord:
    location_id: str
    name:        str
    area:        str
    city:        Optional[str] = None
    risk_level:  str = "MEDIUM"
    gas_hazards: Optional[str] = None
    ventilated:  int = 0
    notes:       Optional[str] = None


@dataclass
class AssignmentRecord:
    device_id:   str
    worker_id:   str
    location_id: Optional[str] = None
    active:      int = 1
    returned_at: Optional[str] = None


# ─── Base ─────────────────────────────────────────────────────────────────────

class SQLiteRepository:
    """
    Base: gerencia a conexão e o schema.

    Args:
        db_path: caminho do arquivo .db, ou ':memory:' para testes.
        apply_schema: se True, executa schema.sql na primeira conexão.
    """

    def __init__(
        self,
        db_path: str = SQLITE_DB_PATH,
        apply_schema: bool = True,
    ):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True) \
            if db_path != ":memory:" else None

        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._connect(apply_schema)

    # ------------------------------------------------------------------
    def _connect(self, apply_schema: bool) -> None:
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # permitir uso em múltiplas threads
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row  # acesso por nome de coluna
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

        if apply_schema and os.path.exists(_SCHEMA_PATH):
            with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
                self._conn.executescript(f.read())
            log.info("Schema SQLite aplicado: %s", _SCHEMA_PATH)

    @contextmanager
    def _tx(self):
        """Context manager para transações automáticas com rollback em erro."""
        try:
            yield self._conn
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            log.error("SQLite rollback: %s", e)
            raise

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ─── DeviceRepository ─────────────────────────────────────────────────────────

class DeviceRepository(SQLiteRepository):
    """CRUD de EPIs (tabela 'devices')."""

    def register(self, device: DeviceRecord) -> None:
        """
        Insere um novo EPI. Falha se device_id já existir.
        Use update_status para alterar dispositivos existentes.
        """
        with self._tx():
            self._conn.execute(
                """INSERT INTO devices
                   (device_id, model, manufacturer, serial_number,
                    calibration_date, next_calibration, status, gas_targets, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (device.device_id, device.model, device.manufacturer,
                 device.serial_number, device.calibration_date,
                 device.next_calibration, device.status,
                 device.gas_targets, device.notes),
            )
        log.info("EPI registrado: %s", device.device_id)

    def get_by_id(self, device_id: str) -> Optional[DeviceRecord]:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        if row is None:
            return None
        return DeviceRecord(
            device_id=row["device_id"], model=row["model"],
            manufacturer=row["manufacturer"], serial_number=row["serial_number"],
            calibration_date=row["calibration_date"],
            next_calibration=row["next_calibration"],
            status=row["status"], gas_targets=row["gas_targets"],
            notes=row["notes"],
        )

    def update_status(self, device_id: str, status: str) -> bool:
        """Atualiza o status de um EPI. Retorna True se encontrado."""
        with self._tx():
            cursor = self._conn.execute(
                "UPDATE devices SET status = ? WHERE device_id = ?",
                (status, device_id),
            )
        return cursor.rowcount > 0

    def list_all(self, status: Optional[str] = None) -> list[DeviceRecord]:
        """Lista EPIs, opcionalmente filtrando por status."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM devices WHERE status = ? ORDER BY device_id",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM devices ORDER BY device_id"
            ).fetchall()
        return [
            DeviceRecord(
                device_id=r["device_id"], model=r["model"],
                manufacturer=r["manufacturer"], serial_number=r["serial_number"],
                calibration_date=r["calibration_date"],
                next_calibration=r["next_calibration"],
                status=r["status"], gas_targets=r["gas_targets"],
                notes=r["notes"],
            )
            for r in rows
        ]

    def calibration_alerts(self) -> list[dict]:
        """Retorna EPIs com calibração vencida ou próxima de vencer (30 dias)."""
        rows = self._conn.execute(
            "SELECT * FROM v_calibration_alerts"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, device_id: str) -> bool:
        with self._tx():
            cursor = self._conn.execute(
                "DELETE FROM devices WHERE device_id = ?", (device_id,)
            )
        return cursor.rowcount > 0


# ─── WorkerRepository ─────────────────────────────────────────────────────────

class WorkerRepository(SQLiteRepository):
    """CRUD de funcionários (tabela 'workers')."""

    def register(self, worker: WorkerRecord) -> None:
        with self._tx():
            self._conn.execute(
                """INSERT INTO workers
                   (worker_id, full_name, role, department, phone,
                    emergency_contact, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (worker.worker_id, worker.full_name, worker.role,
                 worker.department, worker.phone,
                 worker.emergency_contact, worker.active),
            )
        log.info("Funcionário registrado: %s", worker.worker_id)

    def get_by_id(self, worker_id: str) -> Optional[WorkerRecord]:
        row = self._conn.execute(
            "SELECT * FROM workers WHERE worker_id = ?", (worker_id,)
        ).fetchone()
        if row is None:
            return None
        return WorkerRecord(
            worker_id=row["worker_id"], full_name=row["full_name"],
            role=row["role"], department=row["department"],
            phone=row["phone"], emergency_contact=row["emergency_contact"],
            active=row["active"],
        )

    def set_active(self, worker_id: str, active: bool) -> bool:
        with self._tx():
            cursor = self._conn.execute(
                "UPDATE workers SET active = ? WHERE worker_id = ?",
                (1 if active else 0, worker_id),
            )
        return cursor.rowcount > 0

    def list_active(self) -> list[WorkerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM workers WHERE active = 1 ORDER BY full_name"
        ).fetchall()
        return [
            WorkerRecord(
                worker_id=r["worker_id"], full_name=r["full_name"],
                role=r["role"], department=r["department"],
                phone=r["phone"], emergency_contact=r["emergency_contact"],
                active=r["active"],
            )
            for r in rows
        ]

    def list_all(self) -> list[WorkerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM workers ORDER BY full_name"
        ).fetchall()
        return [
            WorkerRecord(
                worker_id=r["worker_id"], full_name=r["full_name"],
                role=r["role"], department=r["department"],
                phone=r["phone"], emergency_contact=r["emergency_contact"],
                active=r["active"],
            )
            for r in rows
        ]


# ─── LocationRepository ───────────────────────────────────────────────────────

class LocationRepository(SQLiteRepository):
    """CRUD de locais de risco (tabela 'locations')."""

    def register(self, loc: LocationRecord) -> None:
        with self._tx():
            self._conn.execute(
                """INSERT INTO locations
                   (location_id, name, area, city, risk_level,
                    gas_hazards, ventilated, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (loc.location_id, loc.name, loc.area, loc.city,
                 loc.risk_level, loc.gas_hazards, loc.ventilated, loc.notes),
            )
        log.info("Local registrado: %s", loc.location_id)

    def get_by_id(self, location_id: str) -> Optional[LocationRecord]:
        row = self._conn.execute(
            "SELECT * FROM locations WHERE location_id = ?", (location_id,)
        ).fetchone()
        if row is None:
            return None
        return LocationRecord(
            location_id=row["location_id"], name=row["name"],
            area=row["area"], city=row["city"],
            risk_level=row["risk_level"], gas_hazards=row["gas_hazards"],
            ventilated=row["ventilated"], notes=row["notes"],
        )

    def list_by_risk(self, risk_level: str) -> list[LocationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM locations WHERE risk_level = ? ORDER BY name",
            (risk_level,),
        ).fetchall()
        return [
            LocationRecord(
                location_id=r["location_id"], name=r["name"],
                area=r["area"], city=r["city"],
                risk_level=r["risk_level"], gas_hazards=r["gas_hazards"],
                ventilated=r["ventilated"], notes=r["notes"],
            )
            for r in rows
        ]


# ─── AssignmentRepository ─────────────────────────────────────────────────────

class AssignmentRepository(SQLiteRepository):
    """Atribuições EPI ↔ Funcionário (tabela 'assignments')."""

    def assign(self, assignment: AssignmentRecord) -> int:
        """Cria uma nova atribuição e retorna o assignment_id gerado."""
        with self._tx():
            cursor = self._conn.execute(
                """INSERT INTO assignments
                   (device_id, worker_id, location_id, active)
                   VALUES (?, ?, ?, 1)""",
                (assignment.device_id, assignment.worker_id,
                 assignment.location_id),
            )
        assignment_id = cursor.lastrowid
        log.info(
            "Atribuição criada: #%d (%s → %s)",
            assignment_id, assignment.device_id, assignment.worker_id,
        )
        return assignment_id

    def return_device(self, assignment_id: int) -> bool:
        """Marca a devolução do EPI (encerra a atribuição)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._tx():
            cursor = self._conn.execute(
                """UPDATE assignments
                   SET active = 0, returned_at = ?
                   WHERE assignment_id = ?""",
                (now, assignment_id),
            )
        return cursor.rowcount > 0

    def active_assignments(self) -> list[dict]:
        """Retorna todas as atribuições ativas com detalhes (via view)."""
        rows = self._conn.execute("SELECT * FROM v_active_assignments").fetchall()
        return [dict(r) for r in rows]

    def get_by_device(self, device_id: str) -> Optional[dict]:
        """Retorna a atribuição ativa de um dispositivo, se houver."""
        row = self._conn.execute(
            "SELECT * FROM v_active_assignments WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        return dict(row) if row else None
