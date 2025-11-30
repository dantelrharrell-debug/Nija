# gunicorn.conf.py
bind = "0.0.0.0:5000"
workers = 2
threads = 2
worker_class = "gthread"
timeout = 120
loglevel = "debug"
accesslog = "-"
errorlog = "-"
capture_output = True

# debug: do not preload app into master process while debugging imports
preload_app = False

# keep default_proc_name pointing to the expected module
default_proc_name = "web.wsgi:app"
