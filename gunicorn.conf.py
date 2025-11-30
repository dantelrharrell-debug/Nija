import os
import multiprocessing

# Bind to port from environment variable, fallback to 8080
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Worker configuration
worker_class = "gthread"  # alternatives: "gevent", "sync"
workers = multiprocessing.cpu_count() * 2 + 1
threads = 4
timeout = 60
graceful_timeout = 30
keepalive = 2

# Logging
loglevel = "info"  # or "debug" for more verbose logs
accesslog = "-"    # stdout
errorlog = "-"     # stderr
capture_output = True

# Preload app for faster worker spawn
preload_app = True

# Max request line and header size (prevents weird client errors)
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Working directory (optional)
chdir = "/app"

# WSGI application
wsgi_app = "wsgi:app"

# Auto-reload (disable in production)
reload = False
