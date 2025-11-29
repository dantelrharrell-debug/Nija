# gunicorn.conf.py
bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
keepalive = 2
loglevel = "debug"
capture_output = True
errorlog = "-"
accesslog = "-"

# Explicit WSGI app used by gunicorn (ensure this matches your web/wsgi.py)
wsgi_app = "web.wsgi:app"

def post_worker_init(worker):
    """
    Called after a worker boots. Import and call init_bot() here to
    initialize per-worker bot processes safely.
    """
    try:
        # Import using package path that matches your repository layout
        from app import init_bot
        print("post_worker_init: calling init_bot()")
        init_bot()
    except Exception as e:
        # Do NOT let initialization errors crash the worker - just log them
        import sys
        print("post_worker_init error:", repr(e), file=sys.stderr)
