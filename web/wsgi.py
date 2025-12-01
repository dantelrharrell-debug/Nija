import logging
import sys
import os

# ----------------------------
# Add local vendor path first
# ----------------------------
VENDOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../cd/vendor"))
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# ----------------------------
# Setup logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ----------------------------
# Attempt to 
# ----------------------------
try:
    
    logging.info("coinbase_advanced_py module imported. Live trading enabled.")
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced_py module not installed. Live trading disabled.")

# ----------------------------
# Import bot safely
# ----------------------------
try:
    from bot import live_bot_script
    logging.info("Imported bot.live_bot_script successfully")
except ImportError:
    logging.error("Failed to import bot.live_bot_script")

# ----------------------------
# Import app factory and create WSGI app
# ----------------------------
try:
    from web import create_app
    app = create_app()
    logging.info("Flask app created successfully")
except Exception as e:
    logging.exception("Failed to create Flask app: %s", e)
    raise

# ----------------------------
# Optional local run (for dev)
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
