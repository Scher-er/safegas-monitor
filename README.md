# SafeGas Monitor 🛢️🔥

> **Disciplina:** Projetos em Engenharia da Computação I — UNIVAP 2026  
> **Objetivo:** Simular um EPI (Equipamento de Proteção Individual) sensor de gases portátil para ambientes de risco de vazamento, cobrindo toda a camada de software que sustentará o hardware real desenvolvido em Projetos II.

---

## 🏗️ Arquitetura

```
EPI Simulado ──(Socket TCP)──► Central de Comando ──► MongoDB (telemetria)
   └─ ruído gaussiano           └─ Filtros digitais      └─ SQLite (cadastros)
   └─ múltiplos gases           └─ Cálculo LEL_mix        └─ Laudos LaTeX (.tex)
                                └─ Alertas escalonados
```

## 📦 Stack

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ |
| Comunicação | Sockets TCP (stdlib) |
| BD Relacional | SQLite 3 (stdlib) |
| BD NoSQL | MongoDB 7.x + PyMongo |
| Filtros | NumPy (Média Móvel + Kalman) |
| Visualização | Matplotlib |
| Laudos | LaTeX + Jinja2 |

## 🚀 Como executar

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Modo demo (EPI + Central no mesmo processo)
python main.py demo

# 3. Central separada (janela 1)
python main.py server

# 4. EPI simulado (janela 2)
python main.py client
```

## 🧪 Testes

```bash
# Etapa 1 — Sanidade de arquitetura
python tests/test_etapa1.py

# Etapa 2 — Simulador de EPI
python tests/test_etapa2.py

# Demo standalone do simulador
python -m epi_simulator.simulator
```

## 📁 Estrutura

```
SafeGasMonitor/
├── config/             # Configurações centrais e contratos de dados
├── epi_simulator/      # Simulador de sensores (Etapa 2)
├── central_command/    # Servidor, filtros e cálculo de LEL (Etapas 3-5)
├── database/           # SQLite + MongoDB (Etapa 6)
├── reports/            # Gerador de laudos LaTeX (Etapa 7)
└── tests/              # Testes por etapa
```

## 📊 Gases Monitorados

| Gás | LEL (%) | UEL (%) |
|---|---|---|
| CH₄ — Metano | 5.0 | 15.0 |
| CO — Monóxido de Carbono | 12.5 | 74.0 |
| H₂S — Gás Sulfídrico | 4.0 | 44.0 |
| C₃H₈ — Propano | 2.1 | 9.5 |
| C₄H₁₀ — Butano | 1.8 | 8.4 |

## ⚠️ Limiares de Alerta

| Nível | % do LEL_mix | Ação |
|---|---|---|
| NORMAL | < 10% | Monitoramento contínuo |
| ATTENTION | 10–25% | Log especial + aviso |
| WARNING | 25–50% | Alerta ao supervisor |
| **CRITICAL** | **≥ 50%** | **🚨 Notificação Bombeiros + Laudo LaTeX** |

## 🔢 Equação de Le Chatelier (LEL de misturas)

$$LEL_{mix} = \frac{100}{\sum_{i=1}^{n} \frac{C_i}{LEL_i}}$$

Com correção termodinâmica de Zabetakis:

$$LEL_T = LEL_{25°C} \times \left(1 - 0{,}08 \times \frac{T - 25}{100}\right)$$

---

*Projeto acadêmico — UNIVAP 2026*
