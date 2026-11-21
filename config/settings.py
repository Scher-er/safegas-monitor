"""
Configurações centrais do SafeGas Monitor.
Reúne parâmetros de rede, limites físicos dos gases, filtros digitais e caminhos de persistência.
"""

# Rede e mensageria MQTT
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
SOCKET_HOST = MQTT_HOST
SOCKET_PORT = 9000
SOCKET_TIMEOUT_S = 5.0
RECONNECT_INTERVAL_S = 3.0

# Simulador de sensores (EPI)
SAMPLE_RATE_HZ = 1.0

# Limites Inferiores e Superiores de Explosividade (% v/v no ar) - NFPA 325 / ABNT NBR IEC 60079-29-1
GAS_CONFIG = {
    "CH4":   {"name": "Metano",              "lel_percent": 5.0,  "uel_percent": 15.0},
    "CO":    {"name": "Monóxido de Carbono", "lel_percent": 12.5, "uel_percent": 74.0},
    "H2S":   {"name": "Gás Sulfídrico",      "lel_percent": 4.0,  "uel_percent": 44.0},
    "C3H8":  {"name": "Propano (GLP)",       "lel_percent": 2.1,  "uel_percent": 9.5},
    "C4H10": {"name": "Butano (GLP)",        "lel_percent": 1.8,  "uel_percent": 8.4},
}

SIMULATION_BASE_CONCENTRATIONS = {
    "CH4":   0.0,
    "CO":    0.0,
    "H2S":   0.0,
    "C3H8":  0.0,
    "C4H10": 0.0,
}

SIMULATION_NOISE_STD = 0.05
TEMPERATURE_BASE_C = 25.0
TEMPERATURE_NOISE_STD = 0.3

# Filtros digitais
MOVING_AVG_WINDOW = 10
KALMAN_PROCESS_VARIANCE = 1e-4
KALMAN_MEASUREMENT_VARIANCE = 0.1

# Limiares de alerta (% do LEL_mix)
ALERT_LOW_THRESHOLD = 10.0
ALERT_MEDIUM_THRESHOLD = 25.0
ALERT_CRITICAL_THRESHOLD = 50.0

# Bancos de dados
SQLITE_DB_PATH = "database/sql/safegas.db"
MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB_NAME = "safegas_monitor"
MONGO_COLLECTION_TELEMETRY = "telemetry"
MONGO_COLLECTION_INCIDENTS = "incidents"

# Diretórios de saída de laudos e gráficos
REPORT_LOOKBACK_MINUTES = 15
REPORT_HISTORY_SIZE = 120
REPORTS_OUTPUT_DIR = "reports/latex"
CHARTS_OUTPUT_DIR = "reports/charts"
