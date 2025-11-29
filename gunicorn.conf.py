# Gunicorn configuration

bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
graceful_timeout = 120
keepalive = 2
max_requests = 0
max_requests_jitter = 0
capture_output = True
loglevel = "debug"
errorlog = "-"
accesslog = "-"
