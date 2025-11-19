# Procfile

# Web process: serves Flask endpoints for health checks / status
web: gunicorn -w 1 -b 0.0.0.0:$PORT main:app --log-level info

# Worker process: runs the live trading bot continuously
worker: python3 nija_render_worker.py
