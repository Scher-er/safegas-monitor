"""
Fachada de acesso aos repositórios de persistência (SQLite e MongoDB).
"""

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

__all__ = [
    "SQLiteRepository",
    "DeviceRepository",
    "WorkerRepository",
    "LocationRepository",
    "AssignmentRepository",
    "DeviceRecord",
    "WorkerRecord",
    "LocationRecord",
    "AssignmentRecord",
    "MongoTelemetryRepository",
]
