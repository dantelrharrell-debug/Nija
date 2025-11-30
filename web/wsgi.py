# web/wsgi.py
import logging
from web import app  # imports the Flask app from __init__.py

# Optional: configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("web.wsgi")
logger.info("Starting Flask app via Gunicorn")

if __name__ == "__main__":
    # Only used for local testing
    app.run(host="0.0.0.0", port=5000)
