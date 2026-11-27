"""
Utilitarios para inicializar o servico do MongoDB localmente
e cadastrar automaticamente a conexao do projeto no MongoDB Compass.
"""

import glob
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from config.settings import MONGO_DB_NAME, MONGO_URI

log = logging.getLogger(__name__)


def is_mongo_running(host: str = "127.0.0.1", port: int = 27017, timeout: float = 1.0) -> bool:
    """Verifica se a porta do servidor MongoDB esta aberta e respondendo."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _wait_for_mongo(host: str, port: int, max_wait_s: float = 8.0) -> bool:
    """Aguarda ate o servidor MongoDB aceitar conexoes TCP."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        if is_mongo_running(host, port, timeout=0.5):
            return True
        time.sleep(0.4)
    return False


def find_mongod_executable() -> Optional[str]:
    """Localiza o executavel mongod no PATH ou nos diretorios padrao do sistema."""
    in_path = shutil.which("mongod")
    if in_path:
        return in_path

    if platform.system() == "Windows":
        patterns = [
            r"C:\Program Files\MongoDB\Server\*\bin\mongod.exe",
            r"C:\Program Files (x86)\MongoDB\Server\*\bin\mongod.exe",
        ]
        found = []
        for pattern in patterns:
            found.extend(glob.glob(pattern))
        if found:
            found.sort(reverse=True)
            return found[0]
    else:
        for candidate in ("/usr/bin/mongod", "/usr/local/bin/mongod", "/opt/homebrew/bin/mongod"):
            if os.path.exists(candidate):
                return candidate

    return None


def _try_start_windows_service(host: str, port: int) -> bool:
    """Tenta iniciar o servico do Windows 'MongoDB' caso esteja parado."""
    if platform.system() != "Windows":
        return False

    for cmd in (["sc", "start", "MongoDB"], ["net", "start", "MongoDB"]):
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6,
            )
            if _wait_for_mongo(host, port, max_wait_s=4.0):
                log.info("Servico MongoDB do Windows iniciado automaticamente.")
                return True
        except Exception:
            continue
    return False


def ensure_mongodb_running(
    host: str = "127.0.0.1",
    port: int = 27017,
    data_dir: Optional[str] = None,
) -> tuple[bool, Optional[subprocess.Popen]]:
    """
    Garante que o servidor MongoDB esteja em execucao na maquina local.

    Fluxo:
      1. Se a porta 27017 ja estiver aberta, reutiliza a instancia ativa.
      2. No Windows, tenta iniciar o servico 'MongoDB'.
      3. Se o servico nao subir, localiza o 'mongod' instalado e inicia
         em segundo plano usando uma pasta de dados local do projeto.

    Retorna:
      (ativo, processo_iniciado_pelo_programa_ou_None)
    """
    if is_mongo_running(host, port):
        log.info("MongoDB ja esta em execucao em %s:%d.", host, port)
        return True, None

    if _try_start_windows_service(host, port):
        return True, None

    mongod_bin = find_mongod_executable()
    if not mongod_bin:
        log.warning("Executavel mongod nao encontrado nesta maquina.")
        return False, None

    if not data_dir:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        data_dir = os.path.join(project_root, "database", "nosql", "data")
    os.makedirs(data_dir, exist_ok=True)

    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    mongod_log = os.path.join(log_dir, "mongod.log")

    try:
        cmd = [
            mongod_bin,
            "--dbpath", data_dir,
            "--port", str(port),
            "--bind_ip", host,
            "--logpath", mongod_log,
            "--logappend",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if _wait_for_mongo(host, port, max_wait_s=8.0):
            log.info("MongoDB iniciado automaticamente via %s (dbpath=%s).", mongod_bin, data_dir)
            return True, proc

        proc.terminate()
        log.warning("Processo mongod iniciou mas nao respondeu na porta %d.", port)
        return False, None
    except Exception as e:
        log.warning("Nao foi possivel iniciar o mongod automaticamente: %s", e)
        return False, None


def _get_compass_connections_dir() -> Optional[str]:
    """Retorna o diretorio de conexoes salvas do MongoDB Compass, se instalado."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        base = os.path.join(appdata, "MongoDB Compass")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/MongoDB Compass")
    else:
        base = os.path.expanduser("~/.config/MongoDB Compass")

    if not os.path.exists(base):
        return None

    conn_dir = os.path.join(base, "Connections")
    os.makedirs(conn_dir, exist_ok=True)
    return conn_dir


def ensure_compass_connection(
    connection_name: str = "SafeGas Monitor",
    uri: Optional[str] = None,
) -> bool:
    """
    Verifica se ja existe uma conexao salva para o SafeGas Monitor no
    MongoDB Compass da maquina. Caso nao exista, cria automaticamente o
    arquivo de conexao no diretorio de conexoes do Compass.

    Retorna True se a conexao ja existia ou foi criada com sucesso.
    """
    conn_dir = _get_compass_connections_dir()
    if not conn_dir:
        return False

    target_uri = uri or f"{MONGO_URI.rstrip('/')}/{MONGO_DB_NAME}"

    # Verifica se a conexao ja existe em algum arquivo JSON do Compass
    for fname in os.listdir(conn_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(conn_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            info = data.get("connectionInfo", {})
            fav_name = (info.get("favorite") or {}).get("name", "")
            conn_str = (info.get("connectionOptions") or {}).get("connectionString", "")
            if fav_name.strip().lower() == connection_name.strip().lower() or MONGO_DB_NAME in conn_str:
                return True
        except Exception:
            continue

    # Cria o arquivo de conexao padrao do MongoDB Compass
    conn_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    payload = {
        "_id": conn_id,
        "connectionInfo": {
            "id": conn_id,
            "lastUsed": now_iso,
            "favorite": {
                "name": connection_name,
                "color": "color3",
            },
            "savedConnectionType": "favorite",
            "connectionOptions": {
                "connectionString": target_uri,
                "oidc": {},
            },
        },
        "version": 1,
    }

    dest_file = os.path.join(conn_dir, f"{conn_id}.json")
    try:
        with open(dest_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        log.info("Conexao '%s' criada automaticamente no MongoDB Compass (%s).", connection_name, target_uri)
        return True
    except Exception as e:
        log.warning("Nao foi possivel criar a conexao no MongoDB Compass: %s", e)
        return False
