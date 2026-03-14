#!/usr/bin/env bash
# ============================================================
# BegrijpendTuben – Start script (macOS / Linux)
# chmod +x run.sh && ./run.sh
# ============================================================

set -e
cd "$(dirname "$0")"

echo ""
echo " ==================================="
echo "  BegrijpendTuben opzetten..."
echo " ==================================="
echo ""

# Maak venv aan als die nog niet bestaat
if [ ! -f ".venv/bin/activate" ]; then
    echo " Virtuele omgeving aanmaken..."
    python3 -m venv .venv
fi

# Activeer venv
source .venv/bin/activate

# Installeer dependencies
echo " Pakketten installeren / controleren..."
pip install -r requirements.txt --quiet

echo ""
echo " ==================================="
echo "  App starten op http://localhost:5000"
echo "  Druk op Ctrl+C om te stoppen"
echo " ==================================="
echo ""

python app.py
