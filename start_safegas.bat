@echo off
color 0B
echo ==================================================
echo         INICIANDO SAFEGAS MONITOR (MQTT + Flask)
echo ==================================================
echo.

REM Caminho fixo para a pasta do projeto
cd /d "C:\Users\scher\OneDrive(OG)\Desktop\Universidade\Projeto em Engenharia de Software\SafeGasMonitor"

echo Abrindo o Web Dashboard no navegador padrao...
start http://localhost:8000

echo Iniciando o Sistema Integrado...
echo Mantenha esta janela aberta. Fechar esta janela encerrara TODO o projeto.
echo.
python run_central.py
