# bot/__init__.py
import logging
from flask import Flask

# ========================
# Coinbase Advanced Import
# ========================
try:
    import coinbase_advanced_py
    logging.info("coinbase_advanced_py imported successfully. Live trading enabled.")
except ModuleNotFoundError:
    coinbase_advanced_py = None
    logging.warning("coinbase_advanced_py module not found. Live trading disabled.")

# ========================
# Import bot logic
# ========================
try:
    from . import live_bot_script  # Your main trading logic
    logging.info("Imported bot.live_bot_script successfully")
except Exception as e:
    logging.error(f"Failed to import bot.live_bot_script: {e}")

# ========================
# Create Flask App
# ========================
def create_app():
    app = Flask(__name__)
    
    # Example simple health check route
    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app

# Expose app for Gunicorn
app = create_app()
logging.info("Flask app created successfully")
