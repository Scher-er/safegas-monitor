-- SafeGas Monitor - Script de Carga Inicial de Dados (Seed SQL)
-- Executar com: sqlite3 safegas.db < seed.sql

INSERT OR IGNORE INTO devices (device_id, model, manufacturer, serial_number,
    calibration_date, next_calibration, status, gas_targets, notes) VALUES
    ('EPI-001', 'SafeGas Mk.I Multi-Gas', 'SafeGas Lab', 'SG-2026-001',
     '2026-06-15', '2026-12-15', 'ACTIVE', 'CH4,CO,H2S,C3H8,C4H10', 'Unidade principal de monitoramento em subestacao'),
    ('EPI-002', 'SafeGas Mk.I Multi-Gas', 'SafeGas Lab', 'SG-2026-002',
     '2026-07-20', '2027-01-20', 'ACTIVE', 'CH4,CO,H2S,C3H8,C4H10', 'Unidade alocada em camara de valvulas'),
    ('EPI-003', 'SafeGas Mk.I Multi-Gas', 'SafeGas Lab', 'SG-2026-003',
     '2025-12-01', '2026-06-01', 'MAINTENANCE', 'CH4,CO,H2S', 'Em bancada para revisao periodica de sensores');

INSERT OR IGNORE INTO workers (worker_id, full_name, role, department, phone, emergency_contact, active) VALUES
    ('F-042', 'Joao Silva',   'Tecnico de Campo',     'Manutencao de Redes', '(12) 99900-0001', '(12) 98811-1001', 1),
    ('F-043', 'Ana Costa',    'Engenheira de Campo',  'Inspecao de Redes',   '(12) 99900-0002', '(12) 98811-1002', 1),
    ('F-044', 'Pedro Souza',  'Tecnico Especialista', 'Manutencao de Gas',   '(12) 99900-0003', '(12) 98811-1003', 1);

INSERT OR IGNORE INTO locations (location_id, name, area, city, risk_level, gas_hazards, ventilated, notes) VALUES
    ('LOC-001', 'Galeria Subterranea Norte',  'Zona Industrial',  'Sao Jose dos Campos', 'HIGH',    'CH4,CO',        0, 'Galeria confinada NR-33'),
    ('LOC-002', 'Camara de Valvulas Sul',     'Zona Residencial', 'Sao Jose dos Campos', 'MEDIUM',  'CH4,C3H8',      1, 'Exaustao mecanica ativa'),
    ('LOC-003', 'Subestacao de Gas Centro',   'Centro',           'Sao Jose dos Campos', 'EXTREME', 'CH4,H2S,CO,C3H8', 0, 'Alta pressao de linha');

INSERT OR IGNORE INTO assignments (device_id, worker_id, location_id, active) VALUES
    ('EPI-001', 'F-042', 'LOC-003', 1),
    ('EPI-002', 'F-043', 'LOC-002', 1);

INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES
    ('alert_dest_email', 'gabriellftavares@gmail.com');
