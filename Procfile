# Web process (Flask API)
web: gunicorn app.main:app --bind 0.0.0.0:$PORT --workers 1

# Background worker process
worker: python3 app/nija_render_worker.py
