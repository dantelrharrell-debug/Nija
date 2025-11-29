"""
web/wsgi.py

- Exposes `application` for Gunicorn: `web.wsgi:application`
- Performs non-fatal checks for optional modules (like coinbase code)
- DOES NOT start the trading loop in the WSGI worker process.
  Running trading logic inside Gunicorn workers is unsafe — use a separate process.
"""

import os
import logging

# try to import your Flask app from app.nija_client (you said your package is app/nija_client)
try:
    # adjust depending on your __init__.py; typically __init__ exposes `app` Flask instance
    from app.nija_client import app as flask_app
except Exception as e:
    logging.exception("Failed to import Flask app from app.nija_client. Creating fallback app.")
    from flask import Flask
    flask_app = Flask(__name__)

# optional sanity check for funded accounts; do not sys.exit()
try:
    from app.nija_client.check_funded import check_funded_accounts
except Exception:
    check_funded_accounts = None
    logging.warning("check_funded_accounts import failed; continuing without funded-account pre-check.")

@flask_app.route("/")
def index():
    # if check_funded_accounts is present, show status; otherwise basic message
    try:
        if callable(check_funded_accounts):
            funded = check_funded_accounts()
            return f"Nija Bot: Webhook server running. Funded accounts ok: {funded}"
    except Exception:
        logging.exception("Error while checking funded accounts.")
    return "Nija Bot: Webhook server running."

# Do not start trading loop here.
# If you *must* start background workers from inside the container, use the scripts/start_all.sh
# which will run the webserver and the bot as separate processes.

application = flask_app  # gunicorn expects this name
