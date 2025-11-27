# gunicorn.conf.py
import os

workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
accesslog = "-"   # stdout
errorlog = "-"    # stderr
loglevel = os.environ.get("LOG_LEVEL", "info")
