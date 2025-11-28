# web/wsgi.py
import os
import sys
import logging

# Add the top-level 'app' directory to python path so we can import nija_client
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(ROOT, "app")
sys.path.insert(0, APP_DIR)

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

try:
    # Import the Flask app object and the check function
    from nija_client import app  # Flask app defined in app/nija_client/__init__.py
    from nija_client.check_funded import check_funded_accounts
except Exception as e:
    logger.exception("[ERROR] nija_client package or check_funded.py missing or failed to import")
    # Exit so gunicorn master process aborts instead of spinning workers
    raise

# Run the funding check once during WSGI import. If it fails, raise so gunicorn exits.
if not check_funded_accounts():
    logger.error("[ERROR] No funded accounts detected. Exiting process to avoid partial startup.")
    # raise an ImportError to cause gunicorn worker to fail startup
    raise RuntimeError("No funded accounts detected (check_funded_accounts returned False).")

# Expose 'app' for gunicorn: web.wsgi:app
