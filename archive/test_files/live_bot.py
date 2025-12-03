# live_bot.py
import os
import logging
import threading
import time
from flask import Flask, jsonify

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------- SDK Import (recommended) ----------
# Use this import because your build logs showed coinbase-advanced-py metadata.
try:
    
    logging.info("Imported coinbase_advanced_py.client.Client")
    LIVE_TRADING_ENABLED = True
except ModuleNotFoundError as e:
    Client = None
    LIVE_TRADING_ENABLED = False
    logging.error("coinbase_advanced_py not installed. Live trading disabled.")
    logging.debug("Import error:", exc_info=e)
except Exception:
    Client = None
    LIVE_TRADING_ENABLED = False
    logging.exception("Unexpected error importing coinbase_advanced_py")

# ---------- Client init ----------
client = None
if LIVE_TRADING_ENABLED and Client is not None:
    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_passphrase=os.environ.get("COINBASE_API_PASSPHRASE")
        )
        logging.info("Coinbase client initialized")
    except Exception:
        logging.exception("Failed to initialize Coinbase client; disabling live trading")
        client = None
        LIVE_TRADING_ENABLED = False

# ---------- Flask app ----------
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

# ---------- Bot logic ----------
def run_bot_once():
    if not LIVE_TRADING_ENABLED or client is None:
        logging.warning("Live trading disabled or client missing; skipping run.")
        return

    try:
        logging.info("Bot run start (read-only)")
        # Example: safe read-only call
        try:
            accounts = client.get_accounts()
            # SDK may return list-like or custom objects — probe safely:
            if accounts is None:
                logging.info("No accounts returned")
            else:
                for a in accounts:
                    try:
                        # best-effort extraction for dict-like or attr-like account
                        if isinstance(a, dict):
                            cur = a.get("currency")
                            bal = a.get("balance", {}).get("amount") if isinstance(a.get("balance"), dict) else a.get("balance")
                        else:
                            cur = getattr(a, "currency", None)
                            bal_attr = getattr(a, "balance", None)
                            bal = getattr(bal_attr, "amount", None) if bal_attr is not None else None
                        logging.info(f"Account: {cur} | Balance: {bal}")
                    except Exception:
                        logging.debug("Failed to inspect account entry", exc_info=True)
        except Exception:
            logging.debug("client.get_accounts() failed or not supported", exc_info=True)

        # TODO: add your trading logic (place orders) here, wrapped in try/except
        logging.info("Bot run end")
    except Exception:
        logging.exception("Unhandled error in run_bot_once")

# ---------- Background loop (controlled) ----------
def bot_loop():
    interval = int(os.environ.get("BOT_INTERVAL", 60))
    logging.info("Background bot loop interval %s seconds", interval)
    while True:
        run_bot_once()
        time.sleep(interval)

def start_background_bot():
    # Only start when deploy config explicitly allows it (prevents multiple workers starting it)
    if os.environ.get("START_BOT", "false").lower() != "true":
        logging.info("START_BOT != 'true' -> not starting background bot in this process")
        return
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    logging.info("Background bot thread started")

start_background_bot()

# ---------- Run server ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("Starting Flask dev server on %s", port)
    app.run(host="0.0.0.0", port=port)
