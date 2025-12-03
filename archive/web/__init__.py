# web/__init__.py
import os
import sys
import threading
import logging
from flask import Flask, jsonify

# Add project root (only if needed)
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.init")

def _try_import_bot():
    """
    Attempt to import start_trading_loop and status_info from bot.live_bot_script.
    Return (start_trading_loop or None, status_info or fallback fn).
    """
    try:
        from bot.live_bot_script import start_trading_loop, status_info  # type: ignore
        logger.info("Imported bot.live_bot_script successfully")
        return start_trading_loop, status_info
    except Exception as exc:
        logger.warning("Could not import bot.live_bot_script: %s", exc)
        def status_info():
            return {"ok": False, "error": "bot.live_bot_script not importable", "detail": str(exc)}
        return None, status_info

def create_app():
    app = Flask(__name__)

    start_trading_loop, status_info = _try_import_bot()

    @app.route("/")
    def index():
        return "NIJA Trading Bot web (create_app) — healthy"

    @app.route("/__diagnose")
    def diagnose():
        info = status_info() if callable(status_info) else {"ok": False, "error": "no status_info"}
        # add safe env visibility (never include secrets)
        info.update({
            "live_trading_env": os.environ.get("LIVE_TRADING", "0"),
            "auto_start_bot": os.environ.get("AUTO_START_BOT", "0"),
            "coinbase_api_key_present": bool(os.environ.get("COINBASE_API_KEY")),
            "coinbase_module_installed": info.get("coinbase_module_installed", None),
            "python_version": sys.version
        })
        return jsonify(info)

    # Auto-start the bot thread **only if** explicitly allowed
    auto_start = os.environ.get("AUTO_START_BOT", "0") == "1"
    if auto_start and start_trading_loop:
        try:
            t = threading.Thread(target=start_trading_loop, daemon=True, name="nija-bot-thread")
            t.start()
            app.logger.info("Started background trading thread: %s", t.name)
        except Exception as exc:
            app.logger.exception("Failed to start trading thread: %s", exc)

    return app
