bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
keepalive = 2

# Point to your WSGI app
wsgi_app = "web.wsgi:app"
