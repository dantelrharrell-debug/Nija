#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
# Use the venv pip to install (cache will speed this up)
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Diagnostics — helpful in logs for debugging during deploys
echo "Python: $(which python) $(python --version)"
python -m pip show coinbase-advanced-py || true
python - <<'PY'
import importlib
try:
    m = importlib.import_module("coinbase_advanced_py")
    print("coinbase_advanced_py path:", getattr(m, "__file__", getattr(m, "__path__", None)))
    print("Has CoinbaseClient?", hasattr(m, "CoinbaseClient"))
except Exception as e:
    print("inspect failed:", e)
PY

# Export port if Render requires it (Render sets $PORT normally)
export PORT=${PORT:-10000}
# Start your gunicorn or flask app using the venv python
# Example (adjust module:app to your Flask app):
gunicorn --bind 0.0.0.0:$PORT nija_live_snapshot:app
