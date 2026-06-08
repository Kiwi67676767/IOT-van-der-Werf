@echo off
title Van der Werf Dashboard

echo ========================================
echo   Van der Werf IoT Dashboard
echo ========================================
echo.

REM Controleer of Python aanwezig is
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [FOUT] Python is niet gevonden.
    echo Installeer Python via https://python.org
    pause
    exit /b 1
)

REM Installeer Flask als het nog niet aanwezig is
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Flask installeren...
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [FOUT] pip install mislukt.
        pause
        exit /b 1
    )
)

echo Dashboard starten op http://localhost:5000
echo Druk Ctrl+C om te stoppen.
echo.
python app.py
pause
