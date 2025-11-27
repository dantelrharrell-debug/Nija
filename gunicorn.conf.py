# gunicorn.conf.py
import multiprocessing
workers = 2
threads = 2
bind = "0.0.0.0:8080"
loglevel = "info"
accesslog = "-"   # stdout
errorlog = "-"    # stdout
