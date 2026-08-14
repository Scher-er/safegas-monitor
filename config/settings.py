"""
SafeGas Monitor — Configurações Centrais
========================================
Todos os parâmetros configuráveis do sistema em um único arquivo.
Modifique aqui sem precisar alterar código de lógica.
"""

# ---------------------------------------------------------------------------
# REDE / SOCKETS
# ---------------------------------------------------------------------------
SOCKET_HOST = "127.0.0.1"   # endereço do servidor (Central de Comando)
SOCKET_PORT = 9000           # porta TCP
SOCKET_TIMEOUT_S = 5.0       # timeout de conexão (segundos)
RECONNECT_INTERVAL_S = 3.0   # intervalo entre tentativas de reconexão

# ---------------------------------------------------------------------------
# SIMULADOR DE SENSORES (EPI)
# ---------------------------------------------------------------------------
SAMPLE_RATE_HZ = 1.0         # taxa de amostragem: 1 leitura por segundo

# Gases monitorados e seus Limites Inferiores de Explosividade (% v/v no ar)
# Fonte: NFPA 325 / ABNT NBR 14022
GAS_CONFIG = {
    "CH4":  {"name": "Metano",           "lel_percent": 5.0,  "uel_percent": 15.0},
    "CO":   {"name": "Monóxido de Carbono","lel_percent": 12.5, "uel_percent": 74.0},
    "H2S":  {"name": "Gás Sulfídrico",   "lel_percent": 4.0,  "uel_percent": 44.0},
    "C3H8": {"name": "Propano (GLP)",    "lel_percent": 2.1,  "uel_percent": 9.5},
    "C4H10":{"name": "Butano (GLP)",     "lel_percent": 1.8,  "uel_percent": 8.4},
}

# Concentrações base de simulação (% v/v) — podem ser ajustadas por cenário
SIMULATION_BASE_CONCENTRATIONS = {
    "CH4":   0.0,   # começa em zero, sobe gradualmente no cenário
    "CO":    0.0,
    "H2S":   0.0,
    "C3H8":  0.0,
    "C4H10": 0.0,
}

SIMULATION_NOISE_STD = 0.05  # desvio padrão do ruído gaussiano (% v/v)
TEMPERATURE_BASE_C   = 25.0  # temperatura ambiente base (°C)
TEMPERATURE_NOISE_STD = 0.3  # variação aleatória de temperatura (°C)

# ---------------------------------------------------------------------------
# FILTROS DIGITAIS
# ---------------------------------------------------------------------------
MOVING_AVG_WINDOW = 10       # tamanho da janela da Média Móvel (amostras)

# Parâmetros do Filtro de Kalman
KALMAN_PROCESS_VARIANCE = 1e-4   # Q: variância do ruído de processo
KALMAN_MEASUREMENT_VARIANCE = 0.1 # R: variância do ruído de medição

# ---------------------------------------------------------------------------
# LIMIARES DE ALERTA (% do LEL_mix)
# ---------------------------------------------------------------------------
ALERT_LOW_THRESHOLD      = 10.0   # % do LEL_mix → ATENÇÃO
ALERT_MEDIUM_THRESHOLD   = 25.0   # % do LEL_mix → ALERTA
ALERT_CRITICAL_THRESHOLD = 50.0   # % do LEL_mix → CRÍTICO (aciona bombeiros + laudo)

# ---------------------------------------------------------------------------
# BANCO DE DADOS
# ---------------------------------------------------------------------------
SQLITE_DB_PATH = "database/sql/safegas.db"

MONGO_URI      = "mongodb://localhost:27017/"
MONGO_DB_NAME  = "safegas_monitor"
MONGO_COLLECTION_TELEMETRY = "telemetry"
MONGO_COLLECTION_INCIDENTS = "incidents"

# ---------------------------------------------------------------------------
# GERAÇÃO DE LAUDOS
# ---------------------------------------------------------------------------
REPORT_LOOKBACK_MINUTES = 15          # janela de dados para o laudo
REPORTS_OUTPUT_DIR      = "reports/latex"
CHARTS_OUTPUT_DIR       = "reports/charts"
