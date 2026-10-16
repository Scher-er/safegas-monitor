import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, jsonify, request, send_from_directory
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ui.tui.state import MonitorState

app = Flask(__name__, static_folder="static")

_monitor_state: Optional[MonitorState] = None
_pipeline_handler: Optional[Any] = None
_sim_manager: Optional[Any] = None

def init_api(state: MonitorState, handler: Optional[Any] = None, sim_manager: Optional[Any] = None):
    global _monitor_state, _pipeline_handler, _sim_manager
    _monitor_state = state
    _pipeline_handler = handler
    _sim_manager = sim_manager

@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not _monitor_state:
        return jsonify({})
    return jsonify(_monitor_state.stats)

@app.route("/api/devices", methods=["GET"])
def get_devices():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
        {
            "device_id": d.device_id,
            "worker_id": d.worker_id,
            "location_id": d.location_id,
            "alert_level": d.alert_level,
            "risk_ratio": d.risk_ratio,
            "temperature_c": d.temperature_c,
            "last_seen": d.last_seen_short,
            "packets": d.packets_received
        }
        for d in _monitor_state.devices
    ])

@app.route("/api/history", methods=["GET"])
def get_history():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
        {
            "timestamp": e.ts_short,
            "device_id": e.device_id,
            "alert_level": e.alert_level,
            "risk_ratio": e.risk_ratio,
            "gases": e.gases
        }
        for e in _monitor_state.alert_history
    ])

@app.route("/api/incidents", methods=["GET"])
def get_incidents():
    if not _monitor_state:
        return jsonify([])
    return jsonify([
        {
            "timestamp": i.ts_short,
            "incident_id": i.incident_id[:8],
            "device_id": i.device_id,
            "peak_risk_ratio": i.peak_risk_ratio,
            "latex_path": i.latex_path
        }
        for i in _monitor_state.incidents
    ])

# ─── Configurações: E-mail de Notificação de Alerta ──────────────────────────

@app.route("/api/settings/email", methods=["GET"])
def get_email_setting():
    email = "gabriellftavares@gmail.com"
    if _pipeline_handler:
        email = _pipeline_handler.dest_email
    else:
        from database.sql.sqlite_repository import SQLiteRepository
        repo = SQLiteRepository()
        email = repo.get_setting("alert_dest_email", "gabriellftavares@gmail.com")
        repo.close()
    return jsonify({"dest_email": email})

@app.route("/api/settings/email", methods=["POST"])
def update_email_setting():
    data = request.get_json(silent=True) or {}
    new_email = data.get("dest_email", "").strip()
    if not new_email or "@" not in new_email or "." not in new_email:
        return jsonify({"success": False, "error": "Por favor, insira um endereço de e-mail válido!"}), 400
    
    if _pipeline_handler:
        _pipeline_handler.set_dest_email(new_email)
    else:
        from database.sql.sqlite_repository import SQLiteRepository
        repo = SQLiteRepository()
        repo.set_setting("alert_dest_email", new_email)
        repo.close()
    
    return jsonify({
        "success": True,
        "dest_email": new_email,
        "message": f"E-mail de alerta atualizado com sucesso para {new_email}!"
    })

# ─── Cadastros: Funcionários e Locais (para formulários) ──────────────────────

@app.route("/api/workers", methods=["GET"])
def get_workers():
    from database.sql.sqlite_repository import WorkerRepository
    repo = WorkerRepository()
    workers = repo.list_active()
    repo.close()
    return jsonify([
        {
            "worker_id": w.worker_id,
            "full_name": w.full_name,
            "role": w.role,
            "department": w.department
        }
        for w in workers
    ])

@app.route("/api/locations", methods=["GET"])
def get_locations():
    from database.sql.sqlite_repository import LocationRepository
    repo = LocationRepository()
    locations = repo.list_all()
    repo.close()
    return jsonify([
        {
            "location_id": l.location_id,
            "name": l.name,
            "risk_level": l.risk_level,
            "area": l.area
        }
        for l in locations
    ])

# ─── Cadastros: Dispositivos EPI ──────────────────────────────────────────────

@app.route("/api/devices/registered", methods=["GET"])
def get_registered_devices():
    from database.sql.sqlite_repository import DeviceRepository, AssignmentRepository
    dev_repo = DeviceRepository()
    devices = dev_repo.list_all()
    dev_repo.close()
    
    assign_repo = AssignmentRepository()
    assignments = {a["device_id"]: a for a in assign_repo.active_assignments()}
    assign_repo.close()
    
    result = []
    for d in devices:
        ass = assignments.get(d.device_id, {})
        result.append({
            "device_id": d.device_id,
            "model": d.model,
            "manufacturer": d.manufacturer or "SafeGas Lab",
            "serial_number": d.serial_number or "-",
            "status": d.status,
            "calibration_date": d.calibration_date,
            "next_calibration": d.next_calibration,
            "gas_targets": d.gas_targets,
            "worker_id": ass.get("worker_id", "-"),
            "worker_name": ass.get("full_name", "Não atribuído"),
            "location_name": ass.get("location_name", "-")
        })
    return jsonify(result)

@app.route("/api/devices/register", methods=["POST"])
def register_device():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    model = data.get("model", "").strip()
    
    if not device_id:
        return jsonify({"success": False, "error": "ID do equipamento é obrigatório (ex: EPI-004)!"}), 400
    if not model:
        return jsonify({"success": False, "error": "Modelo do equipamento é obrigatório!"}), 400
    
    from database.sql.sqlite_repository import DeviceRepository, DeviceRecord, AssignmentRepository
    dev_repo = DeviceRepository()
    if dev_repo.get_by_id(device_id):
        dev_repo.close()
        return jsonify({"success": False, "error": f"O equipamento '{device_id}' já está cadastrado!"}), 400
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    next_cal_default = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
    
    manufacturer = data.get("manufacturer", "").strip() or "SafeGas Lab"
    serial_number = data.get("serial_number", "").strip() or None
    calibration_date = data.get("calibration_date", "").strip() or today_str
    next_calibration = data.get("next_calibration", "").strip() or next_cal_default
    status = data.get("status", "ACTIVE")
    gas_targets = data.get("gas_targets", "CH4,CO,H2S,C3H8,C4H10").strip()
    notes = data.get("notes", "").strip() or None
    
    dev_record = DeviceRecord(
        device_id=device_id,
        model=model,
        manufacturer=manufacturer,
        serial_number=serial_number,
        calibration_date=calibration_date,
        next_calibration=next_calibration,
        status=status,
        gas_targets=gas_targets,
        notes=notes
    )
    
    try:
        dev_repo.register(dev_record)
    except Exception as e:
        dev_repo.close()
        return jsonify({"success": False, "error": f"Erro ao registrar no banco SQLite: {str(e)}"}), 500
    dev_repo.close()
    
    # Atribuição opcional a funcionário e local
    worker_id = data.get("worker_id", "").strip()
    location_id = data.get("location_id", "").strip() or None
    if worker_id:
        assign_repo = AssignmentRepository()
        assign_repo.assign_device(device_id, worker_id, location_id)
        assign_repo.close()
    
    if _pipeline_handler:
        _pipeline_handler.invalidate_device_cache(device_id)
        
    return jsonify({
        "success": True,
        "message": f"Equipamento {device_id} cadastrado com sucesso!",
        "device_id": device_id
    }), 201

# ─── Simulador: Controle Dinâmico de Transmissão de EPIs ──────────────────────

@app.route("/api/simulator/active", methods=["GET"])
def get_active_simulations():
    if not _sim_manager:
        return jsonify([])
    return jsonify(_sim_manager.list_active())

@app.route("/api/simulator/start-device", methods=["POST"])
def start_device_simulation():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    scenario = data.get("scenario", "auto").strip()

    if not device_id:
        return jsonify({"success": False, "error": "ID do equipamento é obrigatório!"}), 400

    global _sim_manager
    if not _sim_manager:
        from epi_simulator.client import SimulationManager
        _sim_manager = SimulationManager(host="127.0.0.1", port=1883)
        _sim_manager.start()

    worker_id = data.get("worker_id")
    location_id = data.get("location_id")
    try:
        from database.sql.sqlite_repository import AssignmentRepository
        assign_repo = AssignmentRepository()
        for ass in assign_repo.active_assignments():
            if ass["device_id"] == device_id:
                worker_id = worker_id or ass.get("worker_id")
                location_id = location_id or ass.get("location_id")
                break
        assign_repo.close()
    except Exception:
        pass

    worker_id = worker_id or "F-999"
    location_id = location_id or "LOC-001"

    sim = _sim_manager.add_device(
        device_id=device_id,
        worker_id=worker_id,
        location_id=location_id,
        scenario=scenario,
    )

    return jsonify({
        "success": True,
        "message": f"Equipamento {device_id} ativado na simulação em tempo real!",
        "device_id": device_id,
        "scenario": getattr(sim, "scenario", "custom"),
        "worker_id": sim.worker_id,
        "location_id": sim.location_id,
    })

@app.route("/api/simulator/stop-device", methods=["POST"])
def stop_device_simulation():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()

    if not device_id:
        return jsonify({"success": False, "error": "ID do equipamento é obrigatório!"}), 400

    if not _sim_manager:
        return jsonify({"success": True, "message": "Simulador não inicializado"})

    removed = _sim_manager.remove_device(device_id)
    return jsonify({
        "success": True,
        "removed": removed,
        "device_id": device_id,
        "message": f"Simulação do equipamento {device_id} pausada."
    })

# ─── Servir frontend estático no `/` ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)
