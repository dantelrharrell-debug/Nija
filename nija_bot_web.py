# nija_bot_web.py
import os
import signal
import threading
import time
import logging
from flask import Flask, request, jsonify

# -------- Configuration --------
PORT = int(os.environ.get("PORT", 5000))
START_TOKEN = os.environ.get("START_TOKEN", "please-set-a-secret-token")
# How often to log price (seconds)
PRICE_LOG_THROTTLE = float(os.environ.get("PRICE_LOG_THROTTLE", "1.0"))
# Sleep interval of main loop tick (seconds)
LOOP_TICK = float(os.environ.get("LOOP_TICK", "0.5"))

# -------- Logging --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s"
)
logger = logging.getLogger("nija")

# -------- Coinbase client (idempotent per-process) --------
_coinbase_client = None
_client_lock = threading.Lock()

def get_coinbase_client():
    global _coinbase_client
    with _client_lock:
        if _coinbase_client is None:
            try:
                # Try to import your client from nija_client (adjust if different)
                from nija_client import client as coinbase_client_module
                _coinbase_client = coinbase_client_module
                logger.info("✅ CoinbaseClient initialized with API keys (module)")
            except Exception:
                # Fallback: try direct CoinbaseClient constructor if present
                try:
                    from coinbase_advanced_py.client import CoinbaseClient
                    # You probably store keys in env; this is an example placeholder
                    api_key = os.environ.get("COINBASE_API_KEY")
                    api_secret = os.environ.get("COINBASE_API_SECRET")
                    _coinbase_client = CoinbaseClient(api_key=api_key, api_secret=api_secret)
                    logger.info("✅ CoinbaseClient initialized with API keys (class)")
                except Exception as ex:
                    logger.exception("Failed to initialize Coinbase client; continuing with stub. (%s)", ex)
                    # minimal stub so the app can still run
                    class _StubClient:
                        def get_price(self, symbol):
                            return 30000.0
                    _coinbase_client = _StubClient()
        return _coinbase_client

# -------- Trading loop control (per-process) --------
loop_thread = None
loop_lock = threading.Lock()
stop_event = threading.Event()

app = Flask(__name__)

@app.route("/health", methods=["GET", "HEAD"])
def health():
    # Render (and many platforms) will probe with HEAD/GET.
    # Return 200 quickly and DO NOT start or touch trading loop here.
    return ("", 200)

@app.route("/start", methods=["POST", "GET", "HEAD"])
def start():
    # If probe is HEAD or GET, don't start — just respond OK.
    if request.method in ("HEAD", "GET"):
        return ("", 200)

    # Only allow POST to actually start the trading loop
    token = request.args.get("token") or request.headers.get("X-Start-Token")
    if token != START_TOKEN:
        logger.warning("Invalid start token attempt from %s", request.remote_addr)
        return jsonify({"error": "invalid token"}), 403

    global loop_thread
    with loop_lock:
        if loop_thread is not None and loop_thread.is_alive():
            logger.info("Start requested but loop already running (per-process).")
            return jsonify({"status": "already_running"}), 200

        stop_event.clear()
        loop_thread = threading.Thread(target=trading_loop, name="trading-loop", daemon=True)
        loop_thread.start()
        logger.info("Trading loop thread started by POST /start")
        return jsonify({"status": "started"}), 200

@app.route("/stop", methods=["POST"])
def stop():
    token = request.args.get("token") or request.headers.get("X-Start-Token")
    if token != START_TOKEN:
        return jsonify({"error": "invalid token"}), 403
    stop_event.set()
    return jsonify({"status": "stopping"}), 200

def trading_loop():
    client = get_coinbase_client()
    logger.info("🔥 Nija Ultimate AI Trading Loop Started 🔥 (process %s)", os.getpid())

    last_price_log_time = 0.0

    try:
        while not stop_event.is_set():
            # Wrap price fetch in try/except so exceptions don't kill the loop
            price = None
            try:
                if hasattr(client, "get_price"):
                    price = client.get_price("BTC-USD")
                elif hasattr(client, "get_current_price"):
                    price = client.get_current_price("BTC-USD")
                else:
                    # fallback stub or property
                    price = getattr(client, "price", 30000.0)
            except Exception:
                logger.exception("Price fetch failed, continuing loop.")
                price = None

            now = time.time()
            if price is not None and (now - last_price_log_time) >= PRICE_LOG_THROTTLE:
                logger.info("BTC Price: %s", price)
                last_price_log_time = now

            # ===== Place trading logic here =====
            # Make sure order placement is wrapped in try/except and is idempotent or guarded.
            # Example:
            # try:
            #     maybe_place_orders(client, price)
            # except Exception:
            #     logger.exception("Order placement failed")

            time.sleep(LOOP_TICK)
    finally:
        logger.info("Trading loop exiting cleanly for process %s", os.getpid())

# -------- Graceful shutdown for SIGTERM/SIGINT (gunicorn will send SIGTERM) --------
def _handle_term(signum, frame):
    logger.info("Received signal %s, setting stop_event()", signum)
    stop_event.set()
    # wait briefly for loop to exit
    with loop_lock:
        if loop_thread:
            loop_thread.join(timeout=5)
    logger.info("Shutdown handler finished for process %s", os.getpid())

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

if __name__ == "__main__":
    logger.info("Starting Flask dev server (for local dev only).")
    app.run(host="0.0.0.0", port=PORT)
