#!/bin/bash
set -euo pipefail

echo "[INFO] === STARTING NIJA TRADING BOT PRE-FLIGHT ==="
echo "[INFO] Python: $(python -V 2>&1)"
echo "[INFO] Pip: $(pip -V 2>&1)"

echo "[INFO] Pip list (full):"
pip list --format=columns

# Print any installed coinbase-related packages for debugging
python3 - <<'PY'
import pkg_resources, traceback
installed = {d.project_name: d.version for d in pkg_resources.working_set}
coinbase_pkgs = {k:v for k,v in installed.items() if 'coinbase' in k.lower()}
print("PY: coinbase-related installed distributions:", coinbase_pkgs)
PY

echo "[INFO] Launching Gunicorn..."
# Use explicit wsgi:app so gunicorn imports wsgi.py -> app variable
exec gunicorn --workers 2 --threads 2 --timeout 30 --bind 0.0.0.0:5000 wsgi:app
