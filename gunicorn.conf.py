# gunicorn.conf.py

bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 30
graceful_timeout = 30
keepalive = 2
accesslog = "-"
errorlog = "-"
loglevel = "debug"

# Point to your WSGI app
wsgi_app = "web.wsgi:application"
