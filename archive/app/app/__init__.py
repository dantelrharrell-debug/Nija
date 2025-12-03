# /app/app/__init__.py
from flask import Flask
import sys

app = Flask(__name__)

def init_bot():
    """
    Bot startup logic — called from gunicorn.post_worker_init.
    Keep this non-blocking or start background threads from here.
    """
    try:
        # Example safe startup — replace with your real startup
        # from .nija_client import start_bot
        # start_bot()
        print("init_bot() called", file=sys.stderr)
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
