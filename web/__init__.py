# web/__init__.py
import os
import sys
from flask import Flask, jsonify

# Make sure project root is importable (only do this if needed)
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def create_app():
    """
    Factory used by web.wsgi:app -> create_app()
    Keeps imports and bot start optional and safe.
    """
    app = Flask(__name__)

    # Try to import bot.status_info and start_trading_loop safely
    try:
        from bot.live_bot_script import start_trading_loop, status_info
    except Exception as exc:
        # If import fails, expose a minimal diagnostic
        app.logger.warning("Could not import bot.live_bot_script: %s", exc)
        start_trading_loop = None
        def status_info():
            return {"error": "bot.live_bot_script not importable", "detail": str(exc)}

    @app.route("/")
    def index():
        return "NIJA Trading Bot web (create_app) — healthy"

    # Diagnostic endpoint you can curl to see diagnostic JSON
    @app.route("/__diagnose")
    def diagnose():
        info = status_info() if callable(status_info) else {"ok": False, "error": "no status_info"}
        # Add some env visibility (not secrets)
        info.update({
            "live_trading_env": os.environ.get("LIVE_TRADING", "0"),
            "coinbase_api_key_present": bool(os.environ.get("COINBASE_API_KEY")),
            "coinbase_module_installed": info.get("coinbase_module_installed", None)
        })
        return jsonify(info)

    # Optional: start the bot loop in a background thread — only when imported in a real server
    # Leave commented if you prefer to control bot start externally.
    if start_trading_loop:
        import threading
        @app.before_first_request
        def _start_bot_thread():
            # start as daemon so Gunicorn shutdown is clean
            t = threading.Thread(target=start_trading_loop, daemon=True)
            t.name = "nija-bot-thread"
            t.start()
            app.logger.info("Started background trading thread: %s", t.name)

    return app
