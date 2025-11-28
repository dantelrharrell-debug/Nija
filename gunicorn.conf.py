# gunicorn.conf.py
import os

# Configuration from env with sane defaults
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
loglevel = os.environ.get("LOG_LEVEL", "info")

# Logging to stdout / stderr so container platform collects logs
capture_output = True
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")   # "-" means stdout
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")     # "-" means stderr
