wsgi_app = "app.wsgi:wsgi_app"
bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
loglevel = "debug"
