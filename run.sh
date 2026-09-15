#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "==============================================================="
echo "   WebCardio WC1340 Real-Time Clinical ECG Monitor"
echo "==============================================================="

# Activate virtual environment if available, otherwise create
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

export PYTHONPATH="$DIR"

echo ""
echo "Server starting on: http://localhost:8000"
echo "Listening for sensor packets on: TCP 5000 / UDP 5000, 9000"
echo "Press Ctrl+C to stop."
echo "==============================================================="

exec uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
