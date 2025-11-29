# gunicorn.conf.py
import os

PORT = os.environ.get("PORT") or "8080"

bind = f"0.0.0.0:{PORT}"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "debug")
capture_output = True
accesslog = "-"   # logs to stdout
errorlog = "-"    # logs to stdout

# make sure default proc points to our wsgi module/object
default_proc_name = "web.wsgi:application"
