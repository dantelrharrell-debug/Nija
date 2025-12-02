# web/wsgi.py
import logging
import sys
import os

# ----------------------------
# Add local vendor path first
# ----------------------------
VENDOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../cd/vendor"))
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# ----------------------------
# Setup logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------
# Try importing coinbase lib (truthful logging)
# ----------------------------
try:
    import coinbase_advanced_py  # noqa: F401
    logger.info("coinbase_advanced_py module import: OK")
except ModuleNotFoundError:
    logger.warning("coinbase_advanced_py module not installed. Live trading may be disabled.")
except Exception as e:
    logger.exception("Unexpected error importing coinbase_advanced_py: %s", e)

# ----------------------------
# Import the app factory from bot.live_bot_script
# (bot.live_bot_script should define create_app())
# ----------------------------
try:
    from bot.live_bot_script import create_app
    logger.info("Imported bot.live_bot_script.create_app successfully")
except Exception as e:
    logger.exception("Failed to import bot.live_bot_script.create_app: %s", e)
    raise

# ----------------------------
# Create WSGI app instance (exposed as `app`)
# Gunicorn will use web.wsgi:app
# ----------------------------
try:
    app = create_app()
    logger.info("Flask app created successfully")
except Exception as e:
    logger.exception("Failed to create Flask app: %s", e)
    raise

# ----------------------------
# Optional local run (for dev)
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
