# web/__init__.py
import os
import sys
import logging

# Ensure project root is on sys.path so `bot` can be imported if present
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, jsonify

logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)

    # simple root
    @app.route("/")
    def index():
        return "NIJA Trading Web (healthy)"

    @app.route("/__diagnose")
    def diagnose():
        info = {"ok": True}
        # Check START_BOT env
        info["START_BOT"] = os.environ.get("START_BOT", "0")
        # check for coinbase_advanced import
        try:
            import importlib
            coinbase = importlib.import_module("coinbase_advanced")
            info["coinbase_advanced_installed"] = True
            info["coinbase_advanced_version"] = getattr(coinbase, "__version__", "unknown")
        except Exception as e:
            info["coinbase_advanced_installed"] = False
            info["coinbase_advanced_error"] = str(e)

        # check for bot import (but do not start it here)
        try:
            from bot import live_bot_script  # noqa: F401
            info["bot_importable"] = True
        except Exception as e:
            info["bot_importable"] = False
            info["bot_import_error"] = str(e)

        return jsonify(info)

    # start trading loop only if explicitly enabled and import succeeds
    start_bot_flag = os.environ.get("START_BOT", "0") == "1"
    if start_bot_flag:
        try:
            from bot.live_bot_script import start_trading_loop
        except Exception as e:
            logger.exception("Bot requested but import failed: %s", e)
        else:
            import threading
            t = threading.Thread(target=start_trading_loop, daemon=True)
            t.start()
            logger.info("Started trading loop (daemon thread)")

    return app

# convenience for gunicorn import
app = create_app()
