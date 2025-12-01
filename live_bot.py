# live_bot.py
import os
import sys
import logging
import threading
import time
from flask import Flask, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# --- Import the SDK (specific error handling) ---
try:
    # Keep this if that's the package you installed.
    from coinbase_advanced_py.client import Client
    logging.info("Imported coinbase_advanced_py.client.Client successfully")
    LIVE_TRADING_ENABLED = True
except ModuleNotFoundError as e:
    Client = None
    LIVE_TRADING_ENABLED = False
    logging.error("coinbase_advanced_py package not found; live trading disabled.")
    logging.debug("Import error details:", exc_info=e)
except Exception as e:
    # If import fails for other reasons, log full exception
    Client = None
    LIVE_TRADING_ENABLED = False
    logging.exception("Unexpected error importing coinbase_advanced_py")

# --- Initialize client ---
client = None
if LIVE_TRADING_ENABLED and Client is not None:
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE")
        )
        logging.info("Coinbase Client initialized")
    except Exception:
        logging.exception("Failed to initialize Coinbase Client; disabling live trading")
        client = None
        LIVE_TRADING_ENABLED = False

# --- Flask app ---
app = Flask(__name__)
logging.info("Flask app created")

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "live_trading": bool(LIVE_TRADING_ENABLED and client is not None),
        "client_present": bool(client is not None)
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

# --- Bot logic (safe read-only example) ---
def run_bot_once():
    if not LIVE_TRADING_ENABLED or client is None:
        logging.warning("Live trading disabled or client missing; skipping run.")
        return

    try:
        logging.info("Bot run start (read-only)")
        # Example safe call - adapt to SDK method names
        try:
            accounts = client.get_accounts()
            # Best-effort logging of accounts
            for a in getattr(accounts, "__iter__", lambda: [])():
                try:
                    # safe extraction
                    cur = getattr(a, "currency", None) or (a.get("currency") if isinstance(a, dict) else None)
                    bal = getattr(a, "balance", None) or (a.get("balance") if isinstance(a, dict) else None)
                    bal_amount = None
                    if isinstance(bal, dict):
                        bal_amount = bal.get("amount")
                    elif hasattr(bal, "amount"):
                        bal_amount = getattr(bal, "amount", None)
                    logging.info(f"Account: {cur} | Balance: {bal_amount}")
                except Exception:
                    logging.debug("Failed to inspect account item", exc_info=True)
        except Exception:
            logging.debug("client.get_accounts() failed or not supported by SDK", exc_info=True)

        logging.info("Bot run end")
    except Exception:
        logging.exception("Unhandled error in run_bot_once")

# --- Background loop launcher (controlled) ---
def bot_loop():
    interval = int(os.environ.get("BOT_INTERVAL", 60))
    logging.info("Starting bot loop with interval %s seconds", interval)
    while True:
        run_bot_once()
        time.sleep(interval)

def start_background_bot():
    # Controlled start: only if START_BOT is "true" (avoid multiple workers starting the bot)
    if os.environ.get("START_BOT", "false").lower() != "true":
        logging.info("START_BOT is not 'true' -> not starting background bot here")
        return

    # If running under Gunicorn with multiple workers, you may still get multiple starts.
    # Best practice: run this in a dedicated worker/replica.
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    logging.info("Background bot thread started")

# Start the background bot only when explicitly requested by env.
start_background_bot()

# --- Run server (dev) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("Starting Flask dev server on %s", port)
    app.run(host="0.0.0.0", port=port)
