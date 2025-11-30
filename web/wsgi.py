# wsgi.py  (or web/wsgi.py — whatever path your Gunicorn points to; your Gunicorn config shows wsgi:app)
import os
import threading
import logging
from flask import Flask, jsonify

# Use your nija client module
from nija_client import build_client, client as nija_client_instance, check_and_log_accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija-wsgi")

app = Flask(__name__)

# Start Coinbase client in a background thread exactly once
_started = False
def start_if_needed():
    global _started
    if _started:
        return
    try:
        logger.info("wsgi: initializing Coinbase client (build)")
        c = build_client()
        if c:
            logger.info("wsgi: client built; fetching accounts now")
            check_and_log_accounts()
        else:
            logger.warning("wsgi: client not created (check env vars).")
    except Exception:
        logger.exception("wsgi: error while building client")
    _started = True

# If preload_app=True then this import runs in master process; it's okay to start background thread.
t = threading.Thread(target=start_if_needed, daemon=True)
t.start()

# A health route to see accounts quickly
@app.route("/__nija_accounts")
def accounts():
    try:
        # call build_client again if not present; safe idempotent attempt
        from nija_client import client as client_obj
        if client_obj is None:
            # try building one now
            client_now = build_client()
            if client_now:
                # try to read accounts (nija_client.check_and_log_accounts logs them; we'll try to fetch to return)
                try:
                    accounts = client_now.get_accounts()
                    # try to coerce to json-able structure
                    if hasattr(accounts, "to_dict"):
                        accounts = accounts.to_dict()
                    return jsonify({"connected": True, "accounts": accounts})
                except Exception as e:
                    logger.exception("nija_accounts route: failed to fetch accounts after build: %s", e)
                    return jsonify({"connected": True, "error_fetching_accounts": str(e)}), 500
            else:
                return jsonify({"connected": False, "reason": "no-client"}), 503
        else:
            try:
                accounts = client_obj.get_accounts()
                if hasattr(accounts, "to_dict"):
                    accounts = accounts.to_dict()
                return jsonify({"connected": True, "accounts": accounts})
            except Exception as e:
                logger.exception("nija_accounts route: failed to fetch accounts: %s", e)
                return jsonify({"connected": True, "error_fetching_accounts": str(e)}), 500
    except Exception:
        logger.exception("nija_accounts: unexpected")
        return jsonify({"error": "internal"}), 500

# Root simple page
@app.route("/")
def index():
    return "NIJA TRADING BOT — running"

# expose the Flask app as `app` (gunicorn expects wsgi:app)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
