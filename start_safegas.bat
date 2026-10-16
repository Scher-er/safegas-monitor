@echo off
color 0B
echo ==================================================
echo         INICIANDO SAFEGAS MONITOR (MQTT + Flask)
echo ==================================================
echo.

REM Garante a execução a partir do diretório onde o script está localizado
cd /d "%~dp0"

echo Abrindo o Web Dashboard no navegador padrao...
start http://localhost:8000

echo Iniciando o Sistema Integrado...
echo Mantenha esta janela aberta. Fechar esta janela encerrara TODO o projeto.
echo.
python run_central.py
