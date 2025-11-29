# gunicorn.conf.py
bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 30
reload = False

# Must match your wsgi module path
wsgi_app = "web.wsgi:application"
