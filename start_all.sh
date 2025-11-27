#!/bin/bash
set -euo pipefail

echo "[INFO] === STARTING NIJA TRADING BOT PRE-FLIGHT ==="
echo "[INFO] Python: $(python3 -V 2>&1)"
echo "[INFO] Pip: $(pip -V 2>&1)"

echo "[INFO] Pip list (full):"
pip list --format=columns

# Print any installed coinbase-related packages for debugging
python3 - <<'PY'
import pkg_resources
installed = {d.project_name: d.version for d in pkg_resources.working_set}
coinbase_pkgs = {k:v for k,v in installed.items() if 'coinbase' in k.lower()}
print("PY: coinbase-related installed distributions:", coinbase_pkgs)
PY

echo "[INFO] Starting Nija App (Gunicorn)..."
gunicorn --workers 2 --threads 2 --timeout 30 --bind 0.0.0.0:5000 wsgi:app &

echo "[INFO] Starting Nija Trading Bot..."
python3 nija_client.py &

# Wait for both background processes
wait
