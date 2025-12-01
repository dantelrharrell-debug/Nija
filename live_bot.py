# live_bot.py
"""
Full NIJA trading bot (single-file).
Primary import requested: from coinbase_advanced.client import Client
Falls back to other plausible imports if that fails.
Includes a MockClient so the app can run without the real package (useful for CI/deploy when you
can't install locally or to test endpoints).
"""

import os
import logging
import threading
import time
from flask import Flask, jsonify, request

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("nija_live_bot")

# ---------------------------
# Try imports (requested first)
# ---------------------------
Client = None
IMPORTED_AS = None

try:
    # --- user requested (try this first) ---
    from coinbase_advanced.client import Client
    IMPORTED_AS = "coinbase_advanced.client"
    log.info("Imported Client from coinbase_advanced.client")
except Exception as e1:
    # try other reasonable variants observed in your logs/repos
    try:
        from coinbase_advanced_py.client import Client
        IMPORTED_AS = "coinbase_advanced_py.client"
        log.info("Imported Client from coinbase_advanced_py.client")
    except Exception as e2:
        try:
            # package might expose 'coinbase_advanced' (top-level)
            from coinbase_advanced import Client
            IMPORTED_AS = "coinbase_advanced"
            log.info("Imported Client from coinbase_advanced")
        except Exception as e3:
            try:
                # new coinbase SDK variants sometimes use coinbase.rest.RESTClient
                from coinbase.rest import RESTClient as Client
                IMPORTED_AS = "coinbase.rest.RESTClient"
                log.info("Imported RESTClient from coinbase.rest as Client")
            except Exception as e4:
                # No real client available — will use mock
                Client = None
                IMPORTED_AS = None
                log.error("No coinbase client package available; running without live client.")

# ---------------------------
# Mock fallback client (safe for testing)
# ---------------------------
class MockClient:
    def __init__(self, *args, **kwargs):
        self._balances = {"USD": "10000.00", "BTC": "0.002"}
        log.info("Initialized MockClient (no real API calls will be made).")

    def get_accounts(self):
        # return list-like structure similar to many coinbase clients
        return [
            {"currency": k, "balance": {"amount": v}} for k, v in self._balances.items()
        ]

    def place_order(self, **kwargs):
        # return mock order
        log.info(f"[MOCK] place_order called with: {kwargs}")
        return {"id": "mock-order-123", "status": "mock_placed", **kwargs}

    def close(self):
        log.info("MockClient closed.")

# ---------------------------
# Globals / config
# ---------------------------
LIVE_TRADING_ENABLED = os.environ.get("LIVE_TRADING", "0") in ("1", "true", "True", "yes")
BOT_INTERVAL = int(os.environ.get("BOT_INTERVAL", 60))  # seconds
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")

client = None
_client_lock = threading.Lock()

def init_client():
    global client, LIVE_TRADING_ENABLED
    if IMPORTED_AS is None:
        log.warning("No installed coinbase client found; using MockClient.")
        client = MockClient()
        LIVE_TRADING_ENABLED = False
        return

    # If user enabled live trading but missing keys, disable for safety
    if LIVE_TRADING_ENABLED and (not COINBASE_API_KEY or not COINBASE_API_SECRET):
        log.error("LIVE_TRADING requested but API key/secret missing. Disabling live trading.")
        LIVE_TRADING_ENABLED = False

    if LIVE_TRADING_ENABLED:
        try:
            # adapt to Client constructor signatures if necessary
            # Most clients accept api_key/api_secret (and maybe passphrase). We'll try to pass safely.
            try:
                client = Client(
                    api_key=COINBASE_API_KEY,
                    api_secret=COINBASE_API_SECRET,
                    api_passphrase=COINBASE_API_PASSPHRASE
                )
            except TypeError:
                # fallback: some libs expect different param names
                client = Client(COINBASE_API_KEY, COINBASE_API_SECRET)
            log.info(f"Initialized live Client from {IMPORTED_AS}")
        except Exception as e:
            log.exception(f"Failed to initialize live client: {e}")
            log.warning("Falling back to MockClient and disabling LIVE_TRADING.")
            client = MockClient()
            LIVE_TRADING_ENABLED = False
    else:
        # Not live trading — create mock client for endpoints to work
        client = MockClient()

# initialize client at import
init_client()

# ---------------------------
# Flask app (health + simple endpoints)
# ---------------------------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "nija-live-bot",
        "status": "ok",
        "live_trading": LIVE_TRADING_ENABLED,
        "client_imported_as": IMPORTED_AS or "none"
    })

@app.route("/health", methods=["GET"])
def health():
    # quick self-check
    ok = client is not None
    return jsonify({
        "ok": ok,
        "live_trading": LIVE_TRADING_ENABLED,
        "client": IMPORTED_AS or "mock" if isinstance(client, MockClient) else "none"
    })

@app.route("/balances", methods=["GET"])
def balances():
    with _client_lock:
        try:
            accounts = client.get_accounts()
            return jsonify({"accounts": accounts})
        except Exception as e:
            log.exception("Error fetching balances")
            return jsonify({"error": str(e)}), 500

@app.route("/place-order", methods=["POST"])
def place_order_endpoint():
    """
    Simple endpoint to place an order (demo). POST JSON body is forwarded to client.place_order.
    This endpoint will be disabled if LIVE_TRADING is False to avoid accidental trades.
    """
    payload = request.get_json(force=True, silent=True) or {}
    if not LIVE_TRADING_ENABLED:
        return jsonify({"error": "live trading disabled"}), 403

    with _client_lock:
        try:
            result = client.place_order(**payload)
            return jsonify({"result": result})
        except Exception as e:
            log.exception("Order placement failed")
            return jsonify({"error": str(e)}), 500

# ---------------------------
# Trading logic (placeholder)
# ---------------------------
def trading_step():
    """
    One iteration of trading logic.
    Put your buy/sell logic here. Keep it idempotent and safe.
    Examples:
      - get_accounts(), get_current_price(), check signals, place small test order, cancel if needed
    """
    with _client_lock:
        try:
            accounts = client.get_accounts()
            log.info("Accounts snapshot:")
            for a in accounts:
                # defensive: different clients have slightly different shapes
                try:
                    currency = a.get("currency", a.get("asset", "unknown"))
                    balance = a.get("balance", {}).get("amount", str(a))
                except Exception:
                    currency = str(a)
                    balance = ""
                log.info(f"  -> {currency} : {balance}")
            # ----- Example placeholder signal -----
            # Add your own real signal detection + sized order logic here.
            # Example (DO NOT UNCOMMENT UNLESS YOU WANT ORDERS):
            # if signal_buy:
            #     resp = client.place_order(product_id="BTC-USD", side="buy", size="0.001", type="market")
            #     log.info(f"Placed order: {resp}")
        except Exception as e:
            log.exception("trading_step failed")

# ---------------------------
# Background bot loop
# ---------------------------
_stop_event = threading.Event()
_bot_thread = None

def bot_loop():
    log.info(f"Bot loop starting (interval={BOT_INTERVAL}s). LIVE_TRADING={LIVE_TRADING_ENABLED}")
    while not _stop_event.is_set():
        start = time.time()
        try:
            trading_step()
        except Exception:
            log.exception("Unhandled error in trading loop")
        elapsed = time.time() - start
        wait = max(0, BOT_INTERVAL - elapsed)
        _stop_event.wait(wait)
    log.info("Bot loop stopped.")

def start_bot_thread():
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        log.info("Bot thread already running.")
        return
    _stop_event.clear()
    _bot_thread = threading.Thread(target=bot_loop, daemon=True, name="nija-bot-thread")
    _bot_thread.start()
    log.info("Bot thread started.")

def stop_bot_thread():
    _stop_event.set()
    if _bot_thread:
        _bot_thread.join(timeout=5)
        log.info("Bot thread join attempted.")

# Auto-start thread if desired (default: do NOT auto-start unless env set)
if os.environ.get("AUTO_START_BOT", "0") in ("1", "true", "True"):
    start_bot_thread()
else:
    log.info("AUTO_START_BOT not set, bot will NOT auto-start. Use start_bot_thread() to run.")

# ---------------------------
# CLI / WSGI entrypoint
# ---------------------------
def run_forever():
    """
    If you run this file directly (python live_bot.py) it will start Flask and optionally the bot.
    On production with gunicorn, use an app factory pointing to 'app' (gunicorn wsgi:app)
    """
    if os.environ.get("AUTO_START_BOT", "0") in ("1", "true", "True"):
        start_bot_thread()
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting Flask dev server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    run_forever()
