# gunicorn.conf.py

bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
keepalive = 2

# This MUST match your wsgi.py path
wsgi_app = "web.wsgi:app"

# Optional logging
loglevel = "debug"
capture_output = True
errorlog = "-"
accesslog = "-"
