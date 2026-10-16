# SafeGas Monitor 🛢️🔥

> **Disciplina:** Projetos em Engenharia de Software / Engenharia da Computação — UNIVAP 2026  
> **Objetivo:** Sistema integrado de software para monitoramento em tempo real de atmosferas industriais potencialmente explosivas (LEL/LIE) através de múltiplos EPIs (Equipamentos de Proteção Individual) portáteis inteligentes.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![MQTT](https://img.shields.io/badge/MQTT-v2.0%20(1883)-orange.svg)](https://mqtt.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-lightgrey.svg)](https://www.sqlite.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-7.x%20(NoSQL)-forestgreen.svg)](https://www.mongodb.com/)
[![LaTeX](https://img.shields.io/badge/LaTeX-PDF%20Reports-darkblue.svg)](https://www.latex-project.org/)
[![Rich](https://img.shields.io/badge/Rich-Live%20TUI-purple.svg)](https://github.com/Textualize/rich)

---

## 📑 Sumário

- [Visão Geral](#-visão-geral)
- [Arquitetura do Sistema](#️-arquitetura-do-sistema)
- [Stack Tecnológica](#-stack-tecnológica)
- [Gases Monitorados e Limites Físicos](#-gases-monitorados-e-limites-físicos)
- [Classificação de Risco e Limiares de Alerta](#-classificação-de-risco-e-limiares-de-alerta)
- [Modelagem Matemática e Física](#-modelagem-matemática-e-física)
  - [Equação de Le Chatelier (LEL de Misturas)](#equação-de-le-chatelier-lel-de-misturas)
  - [Correção Térmica de Zabetakis](#correção-térmica-de-zabetakis)
  - [Física Avançada do Simulador de EPI](#física-avançada-do-simulador-de-epi)
- [Interfaces de Usuário](#-interfaces-de-usuário)
  - [Web Dashboard (Flask + Chart.js)](#1-web-dashboard-tempo-real-flask--chartjs)
  - [Terminal UI (Rich Live)](#2-terminal-ui-rich-tui)
- [Como Executar](#-como-executar)
  - [Pré-requisitos](#pré-requisitos)
  - [Instalação das Dependências](#1-instalação-das-dependências)
  - [Configuração de Credenciais de E-mail (Opcional)](#2-configuração-de-credenciais-de-e-mail-opcional)
  - [Inicialização do Sistema](#3-inicialização-do-sistema)
- [Testes Automatizados](#-testes-automatizados)
- [Estrutura do Repositório](#-estrutura-do-repositório)
- [Segurança e Resiliência](#-segurança-e-resiliência)

---

## 🎯 Visão Geral

O **SafeGas Monitor** é uma plataforma que atua como **Central de Comando Industrial** conectada a múltiplos detectores multigás de EPI portáteis via rede sem fio IoT (protocolo MQTT). O sistema recebe telemetria contínua, filtra sinais ruidosos em tempo real com **Filtro de Kalman**, calcula o risco explosivo composto (\(LEL_{\text{mix}}\)) sob a **Lei de Le Chatelier** com compensação de temperatura de **Zabetakis**, gerencia cadastros institucionais de funcionários e áreas de risco em banco relacional **SQLite**, persiste telemetria histórica em **MongoDB**, e gera laudos periciais automáticos compilados em **PDF via LaTeX**, disparando notificações por e-mail via **SMTP** em caso de emergência crítica.

---

## 🏗️ Arquitetura do Sistema

```
┌────────────────────────────────────────────────────────────────────────┐
│                   DISPOSITIVOS / EPIs EM CAMPO                         │
│   EPI-001 (Vazamento)   EPI-002 (Baseline)   EPI-004 (Novo Dinâmico)   │
│   Física Estocástica    Ornstein-Uhlenbeck   Inércia de Membrana τ90   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Telemetria JSON (1.0 Hz)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  BROKER MQTT LOCAL (Porta 1883)                        │
│                 Tópico: safegas/telemetry/<device_id>                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Subscrição contínua
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 CENTRAL DE COMANDO (PipelineHandler)                   │
│                                                                        │
│  1. Filtragem Digital       ──► Filtro de Kalman 1D + Média Móvel      │
│  2. Cálculo Explosividade   ──► Le Chatelier (LEL_mix) + Zabetakis     │
│  3. Motor de Alertas        ──► NORMAL | ATTENTION | WARNING | CRITICAL│
│  4. Persistência Relacional ──► SQLite (EPIs, Colaboradores, Locais)   │
│  5. Persistência NoSQL      ──► MongoDB (Séries Temporais e Incidentes)│
│  6. Emissão de Laudos       ──► Compilação LaTeX → PDF + Gráficos      │
│  7. Notificador             ──► E-mail SMTP com PDF + Webhooks         │
└─────────────────────┬──────────────────────────────────┬───────────────┘
                      │                                  │
                      ▼                                  ▼
      ┌───────────────────────────────┐  ┌───────────────────────────────┐
      │     DASHBOARD WEB (Flask)     │  │     TERMINAL TUI (Rich)       │
      │    http://localhost:8000      │  │    Monitor ao vivo no shell   │
      │  • Monitoramento em Tempo Real│  │  • Status por dispositivo     │
      │  • Cadastro de EPI e Locais   │  │  • Vazão de pacotes (PPS)     │
      │  • Pop-up de Ativação Rápida  │  │  • Histórico de eventos       │
      │  • Ajuste de E-mail de Alerta │  │  • Log de incidentes         │
      └───────────────────────────────┘  └───────────────────────────────┘
```

---

## 📦 Stack Tecnológica

| Componente | Tecnologia | Finalidade no Projeto |
|---|---|---|
| **Linguagem Base** | Python 3.11+ | Desenvolvimento de toda a camada de processamento e servidores |
| **Mensageria IoT** | MQTT (`paho-mqtt` + `amqtt`) | Protocolo assíncrono pub/sub para telemetria leve dos EPIs (porta 1883) |
| **Filtros Digitais** | NumPy | Implementação do Filtro de Kalman 1D e Filtro de Média Móvel |
| **Banco Relacional** | SQLite 3 (`sqlite3` stdlib) | Gestão institucional de dispositivos, colaboradores, áreas de risco e configurações |
| **Banco NoSQL** | MongoDB 7.x (`pymongo`) | Armazenamento de séries temporais de telemetria bruta/processada e incidentes |
| **Web Dashboard** | Flask 3.x + Chart.js | Interface web responsiva para supervisão ao vivo, cadastros e parametrização |
| **Terminal TUI** | Rich Live | Painel interativo de alta performance no terminal para a equipe de TI/operação |
| **Laudos Periciais** | LaTeX + Jinja2 + pdfLaTeX | Geração automatizada de documentos técnicos comprobatórios em formato PDF |
| **Gráficos** | Matplotlib | Renderização de curvas de evolução temporal de gases anexadas aos laudos |
| **Notificações** | SMTP (`smtplib`) + Requests | Transmissão de alertas críticos com anexo em PDF e acionamento de webhooks |

---

## 📊 Gases Monitorados e Limites Físicos

Os limites inferiores (*LEL*) e superiores (*UEL*) de inflamabilidade são definidos com base nas normas **ABNT NBR IEC 60079-29-1**, **NR-33** e **NFPA 325**:

| Fórmula | Nome Comum | LEL (% v/v) | UEL (% v/v) | Risco Primário |
|:---:|:---|:---:|:---:|:---|
| **$\text{CH}_4$** | Metano (Gás Natural) | **5.0%** | 15.0% | Asfixia e explosão violenta |
| **$\text{CO}$** | Monóxido de Carbono | **12.5%** | 74.0% | Altamente tóxico e inflamável |
| **$\text{H}_2\text{S}$** | Gás Sulfídrico | **4.0%** | 44.0% | Tóxico letal em ppm baixos e combustível |
| **$\text{C}_3\text{H}_8$** | Propano (Fração GLP) | **2.1%** | 9.5% | Gás denso, acúmulo no solo, altamente explosivo |
| **$\text{C}_4\text{H}_{10}$** | Butano (Fração GLP) | **1.8%** | 8.4% | Gás pesado, inflamabilidade extrema |

---

## ⚠️ Classificação de Risco e Limiares de Alerta

A Central avalia a taxa de risco composta:
$$R = \left( \frac{C_{\text{mix}}}{LEL_{\text{mix}}} \right) \times 100\%$$

| Nível de Alerta | Faixa de Risco $R$ | Sinalização na Central | Ação Operacional |
|---|:---:|:---:|---|
| **NORMAL** | $R < 10\%$ | 🟢 Verde | Operação segura. Monitoramento passivo contínuo. |
| **ATTENTION** | $10\% \le R < 25\%$ | 🟡 Amarelo | Concentração detectada. Atenção redobrada e registro de evento. |
| **WARNING** | $25\% \le R < 50\%$ | 🟠 Laranja | Alerta sonoro/visual. Aviso ao supervisor e inspeção de ventilação. |
| **CRITICAL** | **$R \ge 50\%$** | 🔴 **Vermelho** | **Evacuação imediata! Compilação de laudo pericial PDF via LaTeX e envio urgente por e-mail.** |

---

## 🔢 Modelagem Matemática e Física

### Equação de Le Chatelier (LEL de Misturas)
Para uma mistura gasosa contendo $n$ gases combustíveis em concentrações relativas $C_i$:

$$LEL_{\text{mix}} = \frac{100}{\sum_{i=1}^{n} \frac{C_i}{LEL_i}}$$

### Correção Térmica de Zabetakis
Conforme a temperatura ambiente se eleva, a energia necessária para ignição diminui, reduzindo o LEL e aumentando o perigo. A fórmula empírica de Zabetakis ajusta o limiar:

$$LEL_T = LEL_{25^\circ\text{C}} \times \left[ 1 - 0{,}08 \times \left( \frac{T - 25}{100} \right) \right]$$

### Física Avançada do Simulador de EPI
Para superar simulações lineares artificiais, o módulo `epi_simulator` implementa modelos estocásticos e dinâmicos:

1. **Vazamento Dinâmico Não-Linear (`DYNAMIC_LEAK`)**:
   - Curva sigmoidal (polinômio cúbico de Hermite) modelando a liberação sob pressão e acúmulo volumétrico.
   - Vórtices turbulentos (*convective eddies*) modelados por dinâmica autorregressiva com injeção estocástica.
   - Baforadas aleatórias (*puffs*) e arraste de hidrocarbonetos secundários ($\text{C}_3\text{H}_8$ e $\text{C}_4\text{H}_{10}$).
2. **Processo de Ornstein-Uhlenbeck (`STOCHASTIC_DRIFT`)**:
   - Simula a atmosfera de um turno normal e seguro com reversão contínua à média e perturbações microclimáticas:
     $$dX_t = \theta (\mu - X_t) dt + \sigma dW_t$$
3. **Inércia Física da Membrana Sensora ($\tau_{90}$)**:
   - Filtro passa-baixas de absorção molecular:
     $$C_{\text{sensor}}[n] = \alpha C_{\text{inst}} + (1 - \alpha) C_{\text{sensor}}[n-1]$$
   - Elimina variações instantâneas robóticas e reproduz a curva de resposta de sensores reais (como as séries MQ e Figaro).
4. **Ciclos Operacionais com Ventilação (`CYCLIC_VENTING`)**:
   - Elevação durante operações industriais seguida por decaimento exponencial rápido de exaustão HVAC ($e^{-k \cdot t}$).
5. **Inércia Térmica Suave**:
   - Modelagem de massa térmica com micro-deriva gradual.

---

## 🖥️ Interfaces de Usuário

### 1. Web Dashboard em Tempo Real (Flask + Chart.js)
Disponível em `http://localhost:8000`:
- **📡 Em Monitoramento**:
  - Indicadores globais em tempo real (Uptime, Dispositivos Ativos, Vazão de Pacotes PPS e Incidentes Críticos).
  - Tabela dinâmica de EPIs conectados exibindo última leitura, colaborador, risco percentual $R$, nível de alerta e temperatura.
  - Painéis de **Histórico de Eventos Recentes** e **Incidentes Críticos com Laudos Emitidos**.
- **📋 Cadastrados no SQLite**:
  - Listagem completa dos equipamentos registrados no banco relacional institucional.
  - Indicador de status de transmissão em tempo real (`● Ativo` ou botão `▶ Iniciar` para colocar qualquer EPI em funcionamento avulso).
- **➕ Cadastro de Novos Equipamentos com Pop-up Interativo**:
  - Registro de novos detectores na base institucional com vínculo a funcionários e locais de risco.
  - **Pop-up de Decisão Imediata**: Ao salvar o equipamento, o sistema pergunta ao operador se deseja adicioná-lo à tela principal e iniciar sua simulação e monitoramento ao vivo imediatamente. Ao confirmar, o backend ativa a telemetria do EPI e redireciona diretamente para o monitoramento ao vivo!
- **⚙️ Configuração Dinâmica de E-mail de Emergência**:
  - Modal para alterar em tempo real o e-mail que receberá os laudos em PDF compilados nos incidentes críticos (persistido no banco SQLite).

### 2. Terminal UI (Rich TUI)
Executado diretamente no console onde a Central é iniciada:
- Layout responsivo com atualização em 4 FPS via `rich.live`.
- Monitoramento de conexões de clientes MQTT.
- Indicador visual colorido por código de alerta ANSI.

---

## 🚀 Como Executar

### Pré-requisitos
* **Python 3.11+** instalado e adicionado ao `PATH`.
* **LaTeX (MiKTeX ou TeX Live)** *(Opcional, mas recomendado)*: Necessário para compilar laudos em PDF (`pdflatex`). Caso não esteja instalado, o sistema opera em modo de contingência gerando o código-fonte `.tex`.
* **MongoDB 7.x** *(Opcional)*: O sistema possui modo degradado automático. Se o MongoDB não estiver ativo, a Central continuará operando normalmente em memória e SQLite.

### 1. Instalação das Dependências
No terminal, dentro da pasta do projeto:
```bash
pip install -r requirements.txt
```

### 2. Configuração de Credenciais de E-mail (Opcional)
Para habilitar o envio real de laudos técnicos em PDF por e-mail via SMTP (Gmail):
1. Copie o arquivo de exemplo:
   ```bash
   cp config/secrets.py.example config/secrets.py
   ```
2. Abra `config/secrets.py` e configure seu e-mail e sua Senha de Aplicativo Google:
   ```python
   SMTP_USER = "seu_email@gmail.com"
   SMTP_PASS = "sua_senha_de_aplicativo_aqui"
   ```
*(O arquivo `config/secrets.py` está protegido no `.gitignore` e nunca será enviado ao GitHub).*

### 3. Inicialização do Sistema

#### Opção A — Execução Rápida via Script (Windows)
Basta dar um duplo clique no arquivo:
```cmd
start_safegas.bat
```
*O script abre automaticamente o navegador em `http://localhost:8000` e inicializa de forma integrada o Broker MQTT, a Central de Comando com Rich TUI, o Servidor Web Flask e o Gerenciador de Simulações.*

#### Opção B — Execução via Linha de Comando
```bash
python run_central.py
```
Em seguida, acesse no navegador: [http://localhost:8000](http://localhost:8000)

> **Encerramento Limpo:** Pressione `Ctrl + C` na janela do terminal para finalizar todos os serviços de forma graciosa. O sistema encerra as conexões MQTT e os subprocessos sem deixar processos zumbis na memória.

---

## 🧪 Testes Automatizados

O projeto conta com baterias de testes unitários e de integração organizados por etapa de desenvolvimento:

```bash
# Teste da Etapa 1 — Sanidade da arquitetura e contratos
python tests/test_etapa1.py

# Teste da Etapa 2 — Simulador de EPI (física, ruído gaussiano, limites e cenários)
python tests/test_etapa2.py

# Teste da Etapa 4 — Filtros digitais (Kalman e Média Móvel)
python tests/test_etapa4.py

# Teste da Etapa 5 — Cálculo LEL_mix e motor de alertas
python tests/test_etapa5.py

# Teste da Etapa 6 — Persistência relacional SQLite e NoSQL MongoDB
python tests/test_etapa6.py

# Teste da Etapa 7 — Geração de laudos técnicos LaTeX e PDF
python tests/test_etapa7.py

# Teste da Etapa 8 — Concorrência e estado compartilhado da TUI
python tests/test_etapa8.py

# Demonstração standalone do simulador no terminal
python -m epi_simulator.simulator
```

---

## 📁 Estrutura do Repositório

```
SafeGasMonitor/
│
├── api/                           # Camada de Apresentação Web (Flask)
│   ├── server.py                  # Endpoints REST e servidor web
│   └── static/                    # Frontend SPA (HTML5, CSS3 moderno, Vanilla JS)
│       ├── index.html             # Interface gráfica com abas e modais
│       ├── style.css              # Tema escuro industrial e responsividade
│       └── app.js                 # Consumo de telemetria e interações
│
├── central_command/               # Núcleo da Central de Comando
│   ├── server.py                  # Cliente MQTT subscriber
│   ├── pipeline_handler.py        # Orquestrador do fluxo de telemetria
│   ├── notifier.py                # Disparador de e-mail SMTP e Webhooks
│   ├── filters/                   # Filtro de Kalman 1D e Média Móvel
│   ├── lel/                       # Algoritmo de Le Chatelier e Zabetakis
│   └── alerts/                    # Motor de classificação de risco e limiares
│
├── config/                        # Configurações e Contratos
│   ├── settings.py                # Constantes do sistema, portas e limiares
│   ├── data_contracts.py          # Dataclasses tipadas (TelemetryPacket, GasReading)
│   ├── secrets.py.example         # Modelo de configuração de credenciais SMTP
│   └── secrets.py                 # Credenciais locais (ignorado no Git)
│
├── database/                      # Persistência Poliglota
│   ├── sql/                       # SQLite (schema.sql e repositórios relacionais)
│   │   ├── schema.sql             # Definição das tabelas e índices relacionais
│   │   ├── sqlite_repository.py   # Repositórios de dispositivos, usuários e locais
│   │   └── safegas.db             # Base SQLite pré-populada
│   └── nosql/                     # MongoDB
│       └── mongo_repository.py    # Repositório de telemetria e incidentes
│
├── epi_simulator/                 # Simulador Físico de Sensores de EPI
│   ├── simulator.py               # Física estocástica, Ornstein-Uhlenbeck e inércia
│   └── client.py                  # SimulationManager multi-dispositivo MQTT
│
├── reports/                       # Emissão de Laudos Técnicos Periciais
│   ├── latex/                     # Laudos gerados (.tex e .pdf)
│   ├── templates/                 # Templates LaTeX com Jinja2
│   └── report_generator.py        # Compilador de relatórios e gerador de gráficos
│
├── ui/                            # Interface Terminal (TUI)
│   └── tui/                       # Layout em Rich e estado sincronizado
│       ├── layout.py              # Grid e painéis da interface Rich
│       └── state.py               # MonitorState thread-safe
│
├── tests/                         # Suíte de testes automatizados por etapa
├── mqtt_broker.py                 # Broker MQTT embutido para execução local
├── run_central.py                 # Ponto de entrada integrado unificado
├── start_safegas.bat              # Inicializador portátil com 1 clique (Windows)
├── requirements.txt               # Dependências do projeto Python
└── README.md                      # Documentação completa do projeto
```

---

## 🔒 Segurança e Resiliência

* **Proteção de Segredos (`.gitignore`)**:
  * Arquivos como `config/secrets.py`, bancos locais com dados de sessão e artefatos de compilação transitórios estão isolados do controle de versão.
* **Degradação Graciosa (Graceful Degradation)**:
  * O sistema não trava se o MongoDB estiver inativo — ele automaticamente registra os alertas e continua operando em modo degradado.
  * Se o utilitário `pdflatex` não estiver disponível no sistema operacional, o laudo pericial é salvo em formato `.tex` legível e devidamente registrado na base de dados.
* **Isolamento de Processos**:
  * O gerenciamento de simulação multi-dispositivo é realizado em threads controladas dentro da mesma aplicação, eliminando o risco de processos zumbis ou vazamento de recursos na máquina do usuário.

---

*Projeto acadêmico — Engenharia da Computação / Engenharia de Software — UNIVAP 2026*
