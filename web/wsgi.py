# web/wsgi.py
import os
import threading
import logging
from flask import jsonify

# Prefer the app factory if present
try:
    # If your factory is web.create_app
    from web import create_app
    app = create_app()
except Exception:
    # Fallback: try to import top-level create_app
    try:
        from create_app import create_app as _factory
        app = _factory()
    except Exception:
        # Last resort: create a minimal app so gunicorn still binds
        from flask import Flask
        app = Flask(__name__)

logger = logging.getLogger("nija-wsgi")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Import nija_client safely (works whether package is app.nija_client or nija_client)
_nija_mod = None
for mod_name in ("app.nija_client", "nija_client"):
    try:
        _nija_mod = __import__(mod_name, fromlist=["build_client", "client", "check_and_log_accounts"])
        break
    except Exception:
        _nija_mod = None

if not _nija_mod:
    logger.warning("Could not import nija_client module. Background trading client won't start.")

_build_lock = threading.Lock()
_started = False
_client = None

def _start_client_once():
    """Build client once (thread-safe). Returns client or None."""
    global _started, _client
    if _started:
        return _client

    with _build_lock:
        if _started:
            return _client
        try:
            logger.info("Initializing Coinbase client (build_client)...")
            # safe attribute access
            build_client = getattr(_nija_mod, "build_client", None) if _nija_mod else None
            if build_client:
                _client = build_client()
                if _client:
                    logger.info("Client built successfully.")
                    # optional: call helper that logs accounts
                    checker = getattr(_nija_mod, "check_and_log_accounts", None)
                    if callable(checker):
                        try:
                            checker()
                        except Exception:
                            logger.exception("check_and_log_accounts failed (non-fatal)")
                else:
                    logger.warning("build_client returned falsy client (check env/credentials).")
            else:
                logger.warning("No build_client() function found in nija_client module.")
        except Exception:
            logger.exception("Error while building Coinbase client")
        _started = True
    return _client

# Start client in background thread in worker process.
def _maybe_start_background():
    if _nija_mod is None:
        return
    t = threading.Thread(target=_start_client_once, daemon=True)
    t.start()

# If Gunicorn uses preload_app=True, we prefer starting in worker after fork.
# Gunicorn will call this if you use the 'post_fork' hook — but we can't assume hooks here.
# Use before_first_request to ensure we start once in the worker process when first request arrives.
@app.before_first_request
def _start_on_first_request():
    _maybe_start_background()

# Also try to start immediately (useful when preload_app=False)
# This runs at import-time (master or worker depending on preload_app); it's harmless because _start_client_once is idempotent.
try:
    _maybe_start_background()
except Exception:
    logger.exception("Failed to spawn background client thread on import; will try on first request.")

# Helper route to inspect accounts
@app.route("/__nija_accounts")
def accounts():
    try:
        # ensure client exists (try building now if necessary)
        client = _client or _start_client_once()
        if not client:
            return jsonify({"connected": False, "reason": "no-client"}), 503
        # call method to get accounts; handle failures
        try:
            accounts = client.get_accounts()
            # convert to JSON-friendly form
            if hasattr(accounts, "to_dict"):
                accounts = accounts.to_dict()
            # If it's a list of objects, try to coerce
            try:
                import json
                json.dumps(accounts)  # quick-check for serializability
            except Exception:
                # best-effort convert
                if isinstance(accounts, (list, tuple)):
                    safe = []
                    for a in accounts:
                        if hasattr(a, "to_dict"):
                            safe.append(a.to_dict())
                        elif hasattr(a, "__dict__"):
                            safe.append(dict(a.__dict__))
                        else:
                            safe.append(str(a))
                    accounts = safe
                else:
                    accounts = str(accounts)
            return jsonify({"connected": True, "accounts": accounts})
        except Exception as e:
            logger.exception("Failed to fetch accounts")
            return jsonify({"connected": True, "error_fetching_accounts": str(e)}), 500
    except Exception:
        logger.exception("Unexpected in accounts route")
        return jsonify({"error": "internal"}), 500

# Root health endpoint
@app.route("/")
def index():
    return "NIJA TRADING BOT — running"

# Expose 'app' variable for Gunicorn (wsgi:app)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
