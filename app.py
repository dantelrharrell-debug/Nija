# app.py
import logging
import traceback
from flask import Flask, jsonify

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOG = logging.getLogger("nija")

# ----------------------------
# Flask app (top-level, as required by gunicorn)
# ----------------------------
app = Flask(__name__)

# runtime flag — default False until we check
_coinbase_available_flag = False

def get_coinbase_flag() -> bool:
    return bool(_coinbase_available_flag)

def _set_coinbase_flag(val: bool):
    global _coinbase_available_flag
    _coinbase_available_flag = bool(val)

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "coinbase_available": get_coinbase_flag()
    })

# ----------------------------
# Coinbase availability check (safe, non-raising)
# ----------------------------
def check_coinbase_available(timeout_seconds: int = 10) -> bool:
    """
    Try to instantiate the CDP client and perform a minimal read-only call.
    This function must not raise; it returns True/False.
    """
    try:
        # import inside function to avoid import-time side effects
        from nija_client import build_client
    except Exception as exc:
        LOG.exception("Could not import build_client from nija_client: %s", exc)
        return False

    try:
        client = build_client()
        LOG.info("Coinbase client instantiated: %s", type(client))

        # Try a few read-only method names that different SDKs expose.
        for method_name in ("get_accounts", "accounts", "list_accounts", "get_wallets", "get_products"):
            try:
                fn = getattr(client, method_name, None)
                if callable(fn):
                    LOG.info("Calling client.%s() for a lightweight health check.", method_name)
                    # Do not assume returned object type — just ensure call doesn't raise.
                    fn()
                    LOG.info("client.%s() succeeded.", method_name)
                    return True
            except Exception as e:
                LOG.debug("client.%s() raised: %s", method_name, e)

        # Last-resort: some clients expose a low-level request method
        if hasattr(client, "request") and callable(getattr(client, "request")):
            try:
                LOG.info("Attempting low-level client.request('GET','/health') if available.")
                client.request("GET", "/health")
                LOG.info("Low-level client.request succeeded.")
                return True
            except Exception as e:
                LOG.debug("Low-level client.request failed: %s", e)

        LOG.warning("No lightweight read-only call succeeded; marking coinbase unavailable.")
        return False

    except Exception as e:
        LOG.exception("Error while checking Coinbase client: %s", e)
        return False

# ----------------------------
# Lazy startup checks (safe)
# ----------------------------
@app.before_first_request
def run_startup_checks():
    LOG.info("Running lazy startup checks (before_first_request).")
    try:
        avail = check_coinbase_available()
        _set_coinbase_flag(avail)
        LOG.info("Coinbase availability: %s", avail)
    except Exception:
        LOG.exception("Unexpected error during lazy startup checks.")
        _set_coinbase_flag(False)

# ----------------------------
# Local dev run
# ----------------------------
if __name__ == "__main__":
    LOG.info("Starting local Flask server (dev only). Running startup checks first.")
    try:
        # run checks synchronously for local dev so health endpoint is accurate
        avail = check_coinbase_available()
        _set_coinbase_flag(avail)
    except Exception:
        LOG.exception("Startup checks failed during local run; continuing to serve.")
        _set_coinbase_flag(False)

    # common local port (you used 8080 in your snippet; adjust if you want 5000)
    app.run(host="0.0.0.0", port=8080, debug=False)
