@echo off
title MetroBot SP 2.0
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ========================================
echo   MetroBot SP 2.0  —  Chat + Mapa
echo  ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://www.python.org/downloads/
    echo Marque a opcao "Add Python to PATH" na instalacao.
    pause
    exit /b 1
)

python -c "import groq, dotenv" 2>nul
if errorlevel 1 (
    echo Instalando dependencias (primeira vez)...
    python -m pip install -q groq python-dotenv
)

echo Abrindo o MetroBot...
echo Converse com a IA e o mapa da rota aparece ao lado.
echo.
python metrobot_app.py
if errorlevel 1 pause
