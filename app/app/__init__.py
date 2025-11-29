# /app/app/__init__.py
from flask import Flask

app = Flask(__name__)

def init_bot():
    """
    Safe place for bot initialization logic.
    DO NOT run this at import time — call from gunicorn.post_worker_init instead.
    Keep this function fast/non-blocking if possible.
    """
    try:
        # Example: import your client and start things here
        # from .nija_client.check_funded import main as start_bot
        # start_bot()
        print("init_bot() called — put bot startup here")
    except Exception as e:
        # Always catch exceptions — don't raise on import or init
        import sys
        print("init_bot error:", repr(e), file=sys.stderr)
