# bot_live.py
import os
import logging
import threading
import time
from flask import Flask, jsonify

# ---------------------------
# Logging Setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------------------------
# Import Coinbase client robustly
# ---------------------------
Client = None
LIVE_TRADING_ENABLED = False
_import_errors = []

# Try the exact import you asked for first (priority)
try:
    from coinbase_advanced.client import Client  # preferred per your request
    logging.info("Imported Client from coinbase_advanced.client")
    LIVE_TRADING_ENABLED = True
except Exception as e:
    _import_errors.append(("coinbase_advanced.client", str(e)))
    # try other plausible names
    try:
        from coinbase_advanced_py.client import Client
        logging.info("Imported Client from coinbase_advanced_py.client")
        LIVE_TRADING_ENABLED = True
    except Exception as e2:
        _import_errors.append(("coinbase_advanced_py.client", str(e2)))
        try:
            # Many versions of the repo expose 'coinbase' as top-level package
            from coinbase.rest import RESTClient as Client
            logging.info("Imported RESTClient from coinbase.rest (aliased to Client)")
            LIVE_TRADING_ENABLED = True
        except Exception as e3:
            _import_errors.append(("coinbase.rest", str(e3)))
            Client = None
            LIVE_TRADING_ENABLED = False

# Log import attempt details
if LIVE_TRADING_ENABLED:
    logging.info("Coinbase client import succeeded.")
else:
    logging.error("Coinbase client import failed. Details:")
    for mod, err in _import_errors:
        logging.error("  Tried %s -> %s", mod, err)

# ---------------------------
# Initialize client if available
# ---------------------------
client = None
if LIVE_TRADING_ENABLED and Client is not None:
    try:
        # The constructor params may differ slightly between packages.
        # We try common environment variable names; adjust if your package expects different args.
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE")
        )
        logging.info("Coinbase client initialized successfully")
    except TypeError:
        # Some Client classes expect different constructor names; try alternate factory methods
        try:
            # Example: some clients use RESTClient(api_key=..., api_secret=...)
            client = Client(os.environ.get("COINBASE_API_KEY"),
                            os.environ.get("COINBASE_API_SECRET"),
                            os.environ.get("COINBASE_API_PASSPHRASE"))
            logging.info("Coinbase client initialized with positional args")
        except Exception as e:
            logging.error("Error initializing Coinbase client: %s", e)
            client = None
            LIVE_TRADING_ENABLED = False
    except Exception as e:
        logging.error("Error initializing Coinbase client: %s", e)
        client = None
        LIVE_TRADING_ENABLED = False

# ---------------------------
# Flask App Setup
# ---------------------------
app = Flask(__name__)
logging.info("Flask app created successfully")

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "live_trading": LIVE_TRADING_ENABLED,
        "client_present": bool(client is not None)
    })

# ---------------------------
# Bot Logic (simple example)
# ---------------------------
def run_bot_once():
    if not LIVE_TRADING_ENABLED or client is None:
        logging.warning("Live trading disabled or client missing; skipping run.")
        return

    try:
        # call a safe, read-only method if available
        # Note: method names vary between packages; we attempt common ones
        accounts = None
        if hasattr(client, "get_accounts"):
            accounts = client.get_accounts()
        elif hasattr(client, "list_accounts"):
            accounts = client.list_accounts()
        elif hasattr(client, "accounts"):
            accounts = client.accounts()
        else:
            logging.warning("No known accounts method on client; introspecting methods.")
            # attempt REST call via a generic GET endpoint (best-effort; non-destructive)
            try:
                # If client exposes .request or .get, call a simple endpoint
                if hasattr(client, "request"):
                    accounts = client.request("GET", "/accounts")
                elif hasattr(client, "get"):
                    accounts = client.get("/accounts")
            except Exception as e:
                logging.error("Generic GET /accounts failed: %s", e)

        if accounts is not None:
            # `accounts` may be a list or a generator; log key fields safely
            try:
                for a in accounts:
                    # safe field access - logs what we can
                    try:
                        if isinstance(a, dict):
                            currency = a.get("currency") or a.get("currency_code") or a.get("asset")
                            balance = a.get("balance", {}).get("amount") if a.get("balance") else a.get("balance")
                            logging.info("Account: %s | Balance: %s", currency, balance)
                        else:
                            logging.info("Account item: %r", a)
                    except Exception:
                        logging.info("Account item (raw): %r", a)
            except TypeError:
                logging.info("Accounts object: %r", accounts)
        else:
            logging.info("No accounts info retrieved (maybe API version mismatch).")

        # (No live order placement in this example - add your trading logic safely here)
        logging.info("Bot run complete.")
    except Exception as e:
        logging.error("Bot execution failed: %s", e)

# ---------------------------
# Background bot loop (non-blocking)
# ---------------------------
def bot_loop():
    interval = int(os.environ.get("BOT_INTERVAL", 60))
    logging.info("Starting background bot loop with interval %s seconds", interval)
    while True:
        run_bot_once()
        time.sleep(interval)

if LIVE_TRADING_ENABLED and client is not None:
    bg = threading.Thread(target=bot_loop, daemon=True)
    bg.start()
    logging.info("Bot background thread started")
else:
    logging.info("Bot background thread not started because live trading is disabled or client missing")

# ---------------------------
# Run Flask when executed directly (Gunicorn will import the module; it should only expose 'app')
# ---------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("Starting Flask development server on port %s", port)
    app.run(host="0.0.0.0", port=port)
