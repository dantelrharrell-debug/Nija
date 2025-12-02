# gunicorn.conf.py
bind = "0.0.0.0:5000"
workers = 2
worker_class = "gthread"
threads = 2
timeout = 120
loglevel = "debug"
capture_output = True
accesslog = "-"
errorlog = "-"
