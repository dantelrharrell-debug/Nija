# gunicorn.conf.py
wsgi_app = "web.wsgi:app"
bind = "0.0.0.0:5000"
workers = 2
worker_class = "gthread"
threads = 2
worker_connections = 1000
timeout = 120
graceful_timeout = 30
capture_output = True
loglevel = "debug"
accesslog = "-"
errorlog = "-"
