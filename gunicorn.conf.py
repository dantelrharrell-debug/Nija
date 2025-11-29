# gunicorn.conf.py
bind = "0.0.0.0:8080"
workers = 2
threads = 2
worker_class = "gthread"
loglevel = "debug"

# point to web.wsgi:application by default (our entrypoint also uses this)
wsgi_app = "web.wsgi:application"
