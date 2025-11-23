# web/wsgi.py
import os
import logging
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)

    @app.route("/_health")
    def health():
        return jsonify({"status": "ok"})

    # Try to register optional TradingView blueprint without failing the whole app
    try:
        from tradingview_webhook import tradingview_blueprint  # <- adjust if your module name differs
        app.register_blueprint(tradingview_blueprint, url_prefix="/tv")
        LOG.info("Registered tradingview_webhook blueprint")
    except Exception as e:
        LOG.warning("Could not register TradingView blueprint: %s", e)

    return app

# Expose module-level app for WSGI servers
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
