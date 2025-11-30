import os
import multiprocessing

# Bind to Railway's dynamic port
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Determine CPU count safely (fallback to 1)
cpu_count = multiprocessing.cpu_count() or 1

# Workers and threads
# Rule of thumb: 2-4 threads per worker, 1 worker per CPU is safe for most bots
workers = max(1, cpu_count)  # at least 1 worker
threads = 2  # threads per worker

# Worker type: gthread is safe for I/O-heavy tasks like bots
worker_class = "gthread"

# Timeouts
timeout = 60           # seconds before force-kill
graceful_timeout = 30  # allow workers to finish ongoing requests
keepalive = 2          # HTTP keep-alive

# Logging
loglevel = "info"     # set to "debug" for verbose logs
accesslog = "-"       # stdout
errorlog = "-"        # stderr
capture_output = True # redirect stdout/stderr

# Preload app for faster worker spawn
preload_app = True

# Request limits (prevents weird client errors)
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Working directory
chdir = "/app"

# WSGI application
wsgi_app = "wsgi:app"

# Reload for development (disable in production)
reload = False
