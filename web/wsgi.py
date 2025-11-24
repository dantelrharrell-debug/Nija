# web/wsgi.py
import logging
import os
import sys

from flask import Flask, jsonify

# Make sure package imports are stable (optional: adjust if your layout differs)
# If your app modules live in /app/bot or /app/src, make sure PYTHONPATH is set in Dockerfile or env.
# sys.path.append(os.path.join(os.path.dirname(__file__), "..", "bot"))  # example if needed

# Configure logging to adopt Gunicorn handlers when running under Gunicorn
gunicorn_logger = logging.getLogger("gunicorn.error")

def create_app():
    app = Flask(__name__)

    # adopt gunicorn logging handlers so logs appear in container logs
    if gunicorn_logger.handlers:
        logging.getLogger().handlers = gunicorn_logger.handlers
        logging.getLogger().setLevel(gunicorn_logger.level or logging.INFO)
    else:
        logging.basicConfig(level=logging.INFO)

    @app.route("/health")
    def health():
        return "OK", 200

    # Try to register the TradingView blueprint. Use defensive import to avoid circular imports.
    try:
        # import the bp and alias, this file expects web.tradingview_webhook exists
        from web.tradingview_webhook import bp as tradingview_bp
        app.register_blueprint(tradingview_bp, url_prefix="/tv")
        app.logger.info("✅ TradingView blueprint registered at /tv")
    except Exception as e:
        app.logger.warning("⚠️ Could not register TradingView blueprint: %s", e)

    # Minimal placeholder for coinbase client init (non-fatal)
    try:
        # If you package a coinbase client under vendor/ or bot/, adjust sys.path above
        sys.path.append(os.path.join(os.path.dirname(__file__), "..", "vendor", "coinbase_advanced_py"))
        from coinbase_advanced_py.client import Client  # optional vendor lib
        API_KEY = os.getenv("COINBASE_API_KEY")
        API_SECRET = os.getenv("COINBASE_API_SECRET")
        API_SUB = os.getenv("COINBASE_API_SUB")
        if API_KEY and API_SECRET and API_SUB:
            client = Client(API_KEY, API_SECRET, API_SUB)
            app.logger.info("✅ Coinbase client initialized (test call skipped).")
        else:
            app.logger.warning("⚠️ Coinbase credentials missing; live trading disabled.")
            client = None
    except Exception:
        app.logger.warning("⚠️ Coinbase client not present or failed to import; live trading disabled.")
        client = None

    @app.route("/trade/status")
    def trade_status():
        if not client:
            return jsonify({"status": "Coinbase not connected"}), 503
        try:
            accounts = client.get_accounts()
            return jsonify({"status": "live", "accounts": accounts}), 200
        except Exception as exc:
            app.logger.exception("Coinbase call failed")
            return jsonify({"status": "error", "message": str(exc)}), 500

    return app

# Expose `app` for Gunicorn
app = create_app()
