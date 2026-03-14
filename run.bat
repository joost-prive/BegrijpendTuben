@echo off
:: ============================================================
:: BegrijpendTuben – Start script (Windows)
:: Dubbelklik dit bestand om de webapp te starten
:: ============================================================

cd /d "%~dp0"

echo.
echo  ===================================
echo   BegrijpendTuben opzetten...
echo  ===================================
echo.

:: Controleer of .venv al bestaat; maak het anders aan
if not exist ".venv\Scripts\activate.bat" (
    echo  Virtuele omgeving aanmaken...
    python -m venv .venv
    if errorlevel 1 (
        echo  FOUT: Python niet gevonden. Installeer Python 3.10+
        pause
        exit /b 1
    )
)

:: Activeer de virtuele omgeving
call .venv\Scripts\activate.bat

:: Installeer packages als ze nog niet aanwezig zijn
echo  Pakketten installeren / controleren...
pip install -r requirements.txt --quiet

echo.
echo  ===================================
echo   App starten op http://localhost:5000
echo   Druk op Ctrl+C om te stoppen
echo  ===================================
echo.

:: Start Flask
python app.py

pause
