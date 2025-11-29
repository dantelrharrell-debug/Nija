# app/wsgi.py
import logging
from flask import Flask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.wsgi")

# Create Flask app (so gunicorn can import app.wsgi:app)
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

# Run funded-account check after startup (non-fatal)
@app.before_first_request
def verify_funded_accounts():
    try:
        # import lazily so missing module doesn't break import time
        from nija_client.check_funded import check_funded_accounts
    except Exception as exc:
        logger.warning("nija_client.check_funded not available: %s. Skipping funded-account check.", exc)
        return

    try:
        ok = check_funded_accounts()
    except Exception as exc:
        logger.error("Error running check_funded_accounts(): %s. Continuing startup.", exc)
        return

    if not ok:
        # Log an error but do not call sys.exit() — that would crash gunicorn workers.
        # If you truly must prevent the service from running without funded accounts,
        # implement that enforcement in your deployment/start script instead of at import time.
        logger.error("No funded accounts detected. Application started but trading features may be disabled.")
    else:
        logger.info("Funded accounts verified.")
