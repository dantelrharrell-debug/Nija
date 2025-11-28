# gunicorn.conf.py
import os

# Worker & threading config
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))

# Binding
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Logging
loglevel = os.environ.get("LOG_LEVEL", "info")
capture_output = True
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
