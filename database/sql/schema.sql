-- SafeGas Monitor — Esquema SQLite — Etapa 6
-- ===========================================
-- Banco relacional para cadastros institucionais:
--   dispositivos EPI, funcionários e locais de risco.
--
-- Executar com: sqlite3 safegas.db < schema.sql
-- Ou via Python: connection.executescript(open("schema.sql").read())
--
-- Referências normativas:
--   ABNT NBR 14022 — EPI para gás
--   ABNT NBR 17505 — Armazenamento de inflamáveis
-- ============================================================

PRAGMA journal_mode = WAL;        -- Write-Ahead Logging para maior performance
PRAGMA foreign_keys = ON;         -- Integridade referencial habilitada

-- ─── Dispositivos EPI ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    device_id          TEXT PRIMARY KEY,           -- ex: "EPI-001"
    model              TEXT NOT NULL,              -- modelo do sensor
    manufacturer       TEXT,                       -- fabricante
    serial_number      TEXT UNIQUE,                -- número de série
    calibration_date   TEXT NOT NULL,              -- ISO 8601 date (YYYY-MM-DD)
    next_calibration   TEXT NOT NULL,              -- próxima calibração (ISO 8601)
    status             TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','MAINTENANCE','RETIRED')),
    gas_targets        TEXT NOT NULL DEFAULT 'CH4,CO,H2S',  -- gases monitorados (CSV)
    registered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes              TEXT
);

-- ─── Funcionários ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workers (
    worker_id          TEXT PRIMARY KEY,           -- matrícula: "F-042"
    full_name          TEXT NOT NULL,
    role               TEXT NOT NULL,              -- ex: "Técnico de Campo"
    department         TEXT NOT NULL,              -- ex: "Manutenção de Redes"
    phone              TEXT,
    emergency_contact  TEXT,
    active             INTEGER NOT NULL DEFAULT 1  -- 1=ativo, 0=inativo
                        CHECK (active IN (0, 1)),
    registered_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Locais de Risco ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS locations (
    location_id        TEXT PRIMARY KEY,           -- ex: "LOC-003"
    name               TEXT NOT NULL,              -- ex: "Galeria Subterrânea Norte"
    area               TEXT NOT NULL,              -- ex: "Zona Industrial"
    city               TEXT,
    risk_level         TEXT NOT NULL DEFAULT 'MEDIUM'
                        CHECK (risk_level IN ('LOW','MEDIUM','HIGH','EXTREME')),
    gas_hazards        TEXT,                       -- gases esperados (CSV)
    ventilated         INTEGER DEFAULT 0           -- 1=sim, 0=não
                        CHECK (ventilated IN (0, 1)),
    registered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes              TEXT
);

-- ─── Atribuições EPI ↔ Funcionário ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id          TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    worker_id          TEXT NOT NULL REFERENCES workers(worker_id) ON DELETE CASCADE,
    location_id        TEXT REFERENCES locations(location_id),
    assigned_at        TEXT NOT NULL DEFAULT (datetime('now')),
    returned_at        TEXT,                       -- NULL enquanto em uso
    active             INTEGER NOT NULL DEFAULT 1
                        CHECK (active IN (0, 1))
);

-- ─── Índices ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_assignments_device  ON assignments(device_id);
CREATE INDEX IF NOT EXISTS idx_assignments_worker  ON assignments(worker_id);
CREATE INDEX IF NOT EXISTS idx_assignments_active  ON assignments(active);
CREATE INDEX IF NOT EXISTS idx_devices_status      ON devices(status);
CREATE INDEX IF NOT EXISTS idx_workers_active      ON workers(active);

-- ─── Views úteis ─────────────────────────────────────────────────────────────

-- Atribuições ativas com detalhes do EPI e funcionário
CREATE VIEW IF NOT EXISTS v_active_assignments AS
SELECT
    a.assignment_id,
    a.assigned_at,
    d.device_id,
    d.model,
    d.status      AS device_status,
    w.worker_id,
    w.full_name,
    w.role,
    l.location_id,
    l.name        AS location_name,
    l.risk_level
FROM assignments a
JOIN devices   d ON d.device_id   = a.device_id
JOIN workers   w ON w.worker_id   = a.worker_id
LEFT JOIN locations l ON l.location_id = a.location_id
WHERE a.active = 1;

-- EPIs com calibração vencida ou próxima de vencer (30 dias)
CREATE VIEW IF NOT EXISTS v_calibration_alerts AS
SELECT
    device_id,
    model,
    calibration_date,
    next_calibration,
    CASE
        WHEN date(next_calibration) < date('now')            THEN 'VENCIDA'
        WHEN date(next_calibration) < date('now', '+30 day') THEN 'PROXIMA'
        ELSE 'OK'
    END AS calibration_status
FROM devices
WHERE status = 'ACTIVE';

-- ─── Dados de seed (desenvolvimento) ─────────────────────────────────────────
INSERT OR IGNORE INTO devices (device_id, model, manufacturer, serial_number,
    calibration_date, next_calibration, status, gas_targets) VALUES
    ('EPI-001', 'SafeGas Mk.I (Simulado)', 'SafeGas Lab', 'SG-SIM-001',
     '2026-01-15', '2026-07-15', 'ACTIVE', 'CH4,CO,H2S,C3H8,C4H10'),
    ('EPI-002', 'SafeGas Mk.I (Simulado)', 'SafeGas Lab', 'SG-SIM-002',
     '2026-02-20', '2026-08-20', 'ACTIVE', 'CH4,CO,H2S'),
    ('EPI-003', 'SafeGas Mk.I (Simulado)', 'SafeGas Lab', 'SG-SIM-003',
     '2025-12-01', '2026-06-01', 'MAINTENANCE', 'CH4,CO');

INSERT OR IGNORE INTO workers (worker_id, full_name, role, department, phone) VALUES
    ('F-042', 'João Silva',   'Técnico de Campo',     'Manutenção de Redes', '(12)99900-0001'),
    ('F-043', 'Ana Costa',    'Engenheira de Campo',  'Inspeção de Redes',   '(12)99900-0002'),
    ('F-044', 'Pedro Souza',  'Técnico Especialista', 'Manutenção de Gás',   '(12)99900-0003');

INSERT OR IGNORE INTO locations (location_id, name, area, city, risk_level, gas_hazards, ventilated) VALUES
    ('LOC-001', 'Galeria Subterrânea Norte',  'Zona Industrial',  'São José dos Campos', 'HIGH',    'CH4,CO',     0),
    ('LOC-002', 'Câmara de Válvulas Sul',     'Zona Residencial', 'São José dos Campos', 'MEDIUM',  'CH4',        0),
    ('LOC-003', 'Subestação de Gás Centro',   'Centro',           'São José dos Campos', 'EXTREME', 'CH4,H2S,CO', 0);

INSERT OR IGNORE INTO assignments (device_id, worker_id, location_id, active) VALUES
    ('EPI-001', 'F-042', 'LOC-003', 1),
    ('EPI-002', 'F-043', 'LOC-002', 1);
