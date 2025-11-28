# gunicorn_conf.py
bind = "0.0.0.0:5000"  # Match EXPOSE 5000
workers = 2
worker_class = "gthread"
threads = 2
worker_connections = 1000
timeout = 120
graceful_timeout = 30
keepalive = 2
accesslog = "-"
errorlog = "-"
loglevel = "debug"
capture_output = True
