"""
SafeGas Monitor — Repositório MongoDB — Etapa 6
================================================
Persistência NoSQL para logs de telemetria de alta frequência.

Usa pymongo. Se o MongoDB não estiver disponível (servidor desligado
ou pymongo não instalado), as operações falham graciosamente com log
de aviso — o servidor continua funcionando sem persistência.

Coleções:
  - telemetry:  um documento por ProcessedReading (1 Hz por EPI)
  - incidents:  um documento por evento CRITICAL

Índices criados automaticamente:
  - telemetry: (device_id, timestamp) → queries de histórico por EPI
  - telemetry: timestamp              → TTL index (retência configurável)
  - incidents: (device_id, triggered_at)

Referências:
  - MongoDB 7.x Document Model: https://www.mongodb.com/docs/manual/core/document/
  - pymongo 4.x: https://pymongo.readthedocs.io/en/stable/
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import logging
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional

from config.settings import (
    MONGO_URI,
    MONGO_DB_NAME,
    MONGO_COLLECTION_TELEMETRY,
    MONGO_COLLECTION_INCIDENTS,
)
from config.data_contracts import ProcessedReading, IncidentRecord, GasReading

log = logging.getLogger(__name__)

# Tentativa de importar pymongo — falha silenciosa se não instalado
try:
    import pymongo
    from pymongo import MongoClient, ASCENDING, DESCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    _PYMONGO_AVAILABLE = True
except ImportError:
    _PYMONGO_AVAILABLE = False
    log.warning("pymongo não instalado. Repositório MongoDB desativado.")

# TTL de documentos de telemetria (em segundos). None = sem expiração.
# Ex: 7 dias = 7 * 24 * 3600 = 604800
_TELEMETRY_TTL_SECONDS: Optional[int] = None


# ─── Utilitários de serialização ──────────────────────────────────────────────

def _processed_to_doc(p: ProcessedReading) -> dict:
    """Converte ProcessedReading em documento MongoDB."""
    doc = {
        "packet_id":          p.packet_id,
        "timestamp":          p.timestamp,
        "device_id":          p.device_id,
        "worker_id":          p.worker_id,
        "location_id":        p.location_id,
        "temperature_c":      p.temperature_c,
        "lel_mix_percent":    p.lel_mix_percent,
        "risk_ratio_percent": p.risk_ratio_percent,
        "alert_level":        p.alert_level,
        "filter_used":        p.filter_used,
        "readings": [
            {
                "gas_id":           r.gas_id,
                "raw_ppm":          r.raw_ppm,
                "raw_percent":      r.raw_percent,
                "filtered_percent": r.filtered_percent,
                "lel_contribution": r.lel_contribution,
            }
            for r in p.readings
        ],
        # Campo para o índice TTL (datetime nativo do Python)
        "_created_at": datetime.now(timezone.utc),
    }
    return doc


def _incident_to_doc(inc: IncidentRecord) -> dict:
    """Converte IncidentRecord em documento MongoDB."""
    return {
        "incident_id":       inc.incident_id,
        "triggered_at":      inc.triggered_at,
        "device_id":         inc.device_id,
        "worker_id":         inc.worker_id,
        "location_id":       inc.location_id,
        "peak_risk_ratio":   inc.peak_risk_ratio,
        "latex_report_path": inc.latex_report_path,
        "resolved_at":       inc.resolved_at,
        "_created_at":       datetime.now(timezone.utc),
    }


# ─── Repositório Principal ────────────────────────────────────────────────────

class MongoTelemetryRepository:
    """
    Repositório MongoDB para telemetria de alta frequência.

    Gerencia as coleções 'telemetry' e 'incidents'.
    Cria índices automaticamente na primeira conexão.

    Modo degradado: se pymongo não estiver instalado ou o MongoDB
    não estiver acessível, todas as operações retornam None/[]
    e logam um aviso — o pipeline continua funcionando sem persistência.
    """

    def __init__(
        self,
        uri: str = MONGO_URI,
        db_name: str = MONGO_DB_NAME,
        server_selection_timeout_ms: int = 3000,
    ):
        """
        Args:
            uri:                          URI de conexão MongoDB
            db_name:                      nome do banco
            server_selection_timeout_ms:  timeout de seleção de servidor (ms)
        """
        self._available = False
        self._client = None
        self._db = None
        self._telemetry = None
        self._incidents = None

        if not _PYMONGO_AVAILABLE:
            log.warning("MongoTelemetryRepository: pymongo indisponível (modo degradado).")
            return

        try:
            self._client = MongoClient(
                uri,
                serverSelectionTimeoutMS=server_selection_timeout_ms,
            )
            # Força a verificação de conectividade
            self._client.admin.command("ping")
            self._db = self._client[db_name]
            self._telemetry = self._db[MONGO_COLLECTION_TELEMETRY]
            self._incidents  = self._db[MONGO_COLLECTION_INCIDENTS]
            self._ensure_indexes()
            self._available = True
            log.info("MongoDB conectado: %s / %s", uri, db_name)
        except Exception as e:
            log.warning(
                "MongoDB indisponível (%s). Operações de telemetria desativadas.", e
            )

    # ------------------------------------------------------------------
    def _ensure_indexes(self) -> None:
        """Cria índices necessários se ainda não existirem."""
        # telemetry: índice composto para queries por EPI + tempo
        self._telemetry.create_index(
            [("device_id", ASCENDING), ("timestamp", DESCENDING)],
            name="idx_device_timestamp",
        )
        # telemetry: índice de alert_level para queries de incidentes
        self._telemetry.create_index("alert_level", name="idx_alert_level")

        # telemetry: TTL index (se configurado)
        if _TELEMETRY_TTL_SECONDS is not None:
            self._telemetry.create_index(
                "_created_at",
                expireAfterSeconds=_TELEMETRY_TTL_SECONDS,
                name="idx_ttl",
            )

        # incidents: índice composto
        self._incidents.create_index(
            [("device_id", ASCENDING), ("triggered_at", DESCENDING)],
            name="idx_incident_device_time",
        )
        log.debug("Índices MongoDB verificados/criados.")

    # ------------------------------------------------------------------
    # Telemetria
    # ------------------------------------------------------------------

    def insert_reading(self, processed: ProcessedReading) -> Optional[str]:
        """
        Insere um ProcessedReading na coleção 'telemetry'.

        Args:
            processed: leitura processada (filtrada + LEL + alerta)

        Returns:
            ID do documento inserido (str), ou None em caso de falha.
        """
        if not self._available:
            return None
        try:
            doc = _processed_to_doc(processed)
            result = self._telemetry.insert_one(doc)
            log.debug(
                "Telemetria inserida: %s → _id=%s",
                processed.packet_id, result.inserted_id,
            )
            return str(result.inserted_id)
        except Exception as e:
            log.error("Erro ao inserir telemetria: %s", e)
            return None

    def get_recent_by_device(
        self,
        device_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        Retorna as últimas 'limit' leituras de um EPI.

        Args:
            device_id: ID do dispositivo EPI
            limit:     número máximo de documentos retornados

        Returns:
            Lista de documentos (dicts), ordenados do mais recente ao mais antigo.
        """
        if not self._available:
            return []
        try:
            cursor = (
                self._telemetry
                .find({"device_id": device_id}, {"_id": 0, "_created_at": 0})
                .sort("timestamp", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            log.error("Erro ao consultar telemetria: %s", e)
            return []

    def get_readings_by_timerange(
        self,
        device_id: str,
        start_iso: str,
        end_iso: str,
    ) -> list[dict]:
        """
        Retorna leituras de um EPI entre dois instantes ISO 8601.

        Args:
            device_id:  ID do EPI
            start_iso:  início do intervalo (ISO 8601, ex: "2026-08-14T10:00:00Z")
            end_iso:    fim do intervalo

        Returns:
            Lista de documentos ordenados por timestamp ascendente.
        """
        if not self._available:
            return []
        try:
            cursor = (
                self._telemetry
                .find({
                    "device_id": device_id,
                    "timestamp": {"$gte": start_iso, "$lte": end_iso},
                }, {"_id": 0, "_created_at": 0})
                .sort("timestamp", ASCENDING)
            )
            return list(cursor)
        except Exception as e:
            log.error("Erro ao consultar intervalo de telemetria: %s", e)
            return []

    def get_critical_events(
        self,
        device_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Retorna eventos com alert_level == 'CRITICAL'.

        Args:
            device_id: filtra por EPI (None = todos os EPIs)
            limit:     máximo de documentos

        Returns:
            Lista de leituras críticas (mais recentes primeiro).
        """
        if not self._available:
            return []
        try:
            query = {"alert_level": "CRITICAL"}
            if device_id:
                query["device_id"] = device_id
            cursor = (
                self._telemetry
                .find(query, {"_id": 0, "_created_at": 0})
                .sort("timestamp", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            log.error("Erro ao consultar eventos críticos: %s", e)
            return []

    def count_by_alert_level(self, device_id: Optional[str] = None) -> dict:
        """
        Retorna a contagem de leituras por nível de alerta.

        Returns:
            {'NORMAL': N, 'ATTENTION': M, 'WARNING': K, 'CRITICAL': J}
        """
        if not self._available:
            return {}
        try:
            match_stage = {}
            if device_id:
                match_stage = {"$match": {"device_id": device_id}}
            pipeline = [
                *([ {"$match": {"device_id": device_id}} ] if device_id else []),
                {"$group": {"_id": "$alert_level", "count": {"$sum": 1}}},
            ]
            result = {doc["_id"]: doc["count"]
                      for doc in self._telemetry.aggregate(pipeline)}
            return result
        except Exception as e:
            log.error("Erro na agregação por nível: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Incidentes
    # ------------------------------------------------------------------

    def insert_incident(self, incident: IncidentRecord) -> Optional[str]:
        """
        Insere um IncidentRecord na coleção 'incidents'.

        Criado automaticamente pelo AlertManager quando alert_level == CRITICAL.

        Returns:
            ID do documento inserido, ou None em caso de falha.
        """
        if not self._available:
            return None
        try:
            doc = _incident_to_doc(incident)
            result = self._incidents.insert_one(doc)
            log.info(
                "Incidente registrado: %s → _id=%s",
                incident.incident_id, result.inserted_id,
            )
            return str(result.inserted_id)
        except Exception as e:
            log.error("Erro ao inserir incidente: %s", e)
            return None

    def get_incidents_by_device(
        self,
        device_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Retorna os últimos incidentes de um EPI."""
        if not self._available:
            return []
        try:
            cursor = (
                self._incidents
                .find({"device_id": device_id}, {"_id": 0, "_created_at": 0})
                .sort("triggered_at", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            log.error("Erro ao consultar incidentes: %s", e)
            return []

    def resolve_incident(self, incident_id: str) -> bool:
        """Marca um incidente como resolvido."""
        if not self._available:
            return False
        try:
            result = self._incidents.update_one(
                {"incident_id": incident_id},
                {"$set": {"resolved_at": datetime.now(timezone.utc).isoformat()}},
            )
            return result.modified_count > 0
        except Exception as e:
            log.error("Erro ao resolver incidente: %s", e)
            return False

    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        """True se a conexão com MongoDB está ativa."""
        return self._available

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._available = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return (
            f"MongoTelemetryRepository("
            f"available={self._available}, "
            f"db={MONGO_DB_NAME})"
        )
