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

# explicit WSGI module
wsgi_app = "web.wsgi:app"

def post_worker_init(worker):
    """
    Called once per worker after it boots. Import and call init_bot() here.
    Wrap in try/except so errors don't kill the worker.
    """
    import sys, traceback
    try:
        # adjust import path if your package name differs
        from app import init_bot
        print("post_worker_init: calling init_bot()", file=sys.stderr)
        init_bot()
    except Exception:
        print("post_worker_init error:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
