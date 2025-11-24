# --- Gunicorn configuration ---
bind = "0.0.0.0:5000"
workers = 1
threads = 1
worker_class = "sync"
timeout = 30
keepalive = 2
loglevel = "debug"
accesslog = "-"
errorlog = "-"
