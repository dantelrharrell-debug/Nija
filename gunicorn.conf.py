import multiprocessing

# Bind to all interfaces on port 8080
bind = "0.0.0.0:8080"

# Use number of CPU cores or at least 1 worker
workers = multiprocessing.cpu_count() or 1

# Worker class for Flask apps
worker_class = "sync"

# Max number of simultaneous clients per worker
worker_connections = 1000

# Timeout in seconds for worker response
timeout = 30
graceful_timeout = 30

# Keep-alive for client connections
keepalive = 2

# Logging
loglevel = "info"
accesslog = "-"   # stdout
errorlog = "-"    # stderr
capture_output = True

# Request limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Preload the app to save memory (optional)
preload_app = False

# Enable auto-reload if needed (dev only)
reload = False
