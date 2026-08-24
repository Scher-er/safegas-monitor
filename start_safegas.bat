@echo off
color 0B
echo ==================================================
echo         INICIANDO SAFEGAS MONITOR
echo ==================================================
echo.

REM Caminho fixo para a pasta do projeto
cd /d "C:\Users\scher\.gemini\antigravity\scratch\SafeGasMonitor"

echo [1/3] Iniciando Central de Comando (Servidor TCP, FastAPI e TUI)...
start "SafeGas - Central de Comando" cmd /k "python run_central.py"

echo Aguardando inicializacao do servidor...
timeout /t 4 /nobreak >nul

echo [2/3] Abrindo o Web Dashboard no navegador padrao...
start http://localhost:8000

echo [3/3] Iniciando o Simulador de Gas (EPI-001)...
start "SafeGas - Simulador de EPI" cmd /k "python -m epi_simulator.client"

echo.
echo Todos os modulos foram iniciados!
echo Fechando este inicializador em 3 segundos...
timeout /t 3 /nobreak >nul
exit
