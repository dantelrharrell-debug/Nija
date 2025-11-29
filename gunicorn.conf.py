# gunicorn.conf.py
bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 30
loglevel = "debug"
capture_output = True
