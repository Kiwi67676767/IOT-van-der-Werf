#!/bin/bash

echo "========================================"
echo "  Van der Werf IoT Dashboard"
echo "========================================"
echo

# Controleer of Python aanwezig is
if ! command -v python3 &> /dev/null; then
    echo "[FOUT] Python is niet gevonden."
    echo "Installeer Python via https://python.org"
    exit 1
fi

# Installeer Flask als het nog niet aanwezig is
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Flask installeren..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[FOUT] pip install mislukt."
        exit 1
    fi
fi

echo "Dashboard starten op http://localhost:5000"
echo "Druk Ctrl+C om te stoppen."
echo
python3 app.py
