# gunicorn.conf.py - conservative production settings
bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 30
keepalive = 2
loglevel = "debug"
capture_output = True
errorlog = "-"
accesslog = "-"
chdir = "/app"
