# web/wsgi.py -- minimal WSGI wrapper that won't re-check PASSPHRASE
import os
import sys
import logging

# add local vendor path first (if you use vendor)
VENDOR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../cd/vendor"))
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Import app factory from bot package
try:
    from bot.live_bot_script import create_app
    app = create_app()
    logger.info("Flask app created successfully")
except Exception:
    logger.exception("Failed to import/create Flask app")
    raise

# For local development
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
