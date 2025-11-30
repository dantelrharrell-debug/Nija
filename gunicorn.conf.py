# gunicorn.conf.py
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
keepalive = 2
loglevel = "debug"
capture_output = True
accesslog = "-"
errorlog = "-"
chdir = "/app"
wsgi_app = "wsgi:app"
import os
