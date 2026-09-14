@echo off
title Gerar MetroBotSP.exe
chcp 65001 >nul
cd /d "%~dp0"

echo Gerando o executavel MetroBotSP.exe ...
python -m pip install -q groq python-dotenv pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name MetroBotSP metrobot_app.py
if errorlevel 1 (
    echo Falhou. Veja o erro acima.
    pause
    exit /b 1
)

if exist "dist\MetroBotSP.exe" (
    copy /Y "dist\MetroBotSP.exe" "MetroBotSP.exe" >nul
    echo.
    echo Pronto: MetroBotSP.exe na pasta do projeto.
    echo Voce pode dar dois cliques nele para conversar com a IA e ver o mapa.
)

pause
