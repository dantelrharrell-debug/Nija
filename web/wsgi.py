# web/wsgi.py
from flask import Flask, jsonify
import logging

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def create_app():
    app = Flask(__name__)

    # Basic health endpoint for Railway / healthchecks
    @app.route("/_health")
    def health():
        return jsonify({"status": "ok"})

    # If you have a TradingView blueprint import it if available
    try:
        # If you previously vendor a tradingview_webhook package or module:
        from tradingview_webhook import tradingview_blueprint  # adjust import as needed
        app.register_blueprint(tradingview_blueprint, url_prefix="/tv")
        LOG.info("Registered tradingview_webhook blueprint")
    except Exception as e:
        LOG.warning("Could not register TradingView blueprint: %s", e)

    # Register any other routes / blueprints here
    return app

# recommended pattern for gunicorn: web.wsgi:app
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 5000)))
