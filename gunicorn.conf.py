# gunicorn.conf.py

# Bind to port 8080
bind = "0.0.0.0:8080"

# Worker config
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
keepalive = 2

# WSGI app
wsgi_app = "web.wsgi:app"  # <-- IMPORTANT: points to your app instance
