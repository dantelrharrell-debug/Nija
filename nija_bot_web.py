# nija_bot_web.py  — example pattern
import os
import threading
import signal
import logging
import time
from flask import Flask, request, jsonify

# --- very simple idempotent client pattern ---
_coinbase_client = None
_client_lock = threading.Lock()

def get_coinbase_client():
    global _coinbase_client
    with _client_lock:
        if _coinbase_client is None:
            # replace with your actual CoinbaseClient import/construct
            from nija_client import client as coinbase_client_module
            # or CoinbaseClient(api_key=..., api_secret=...)
            _coinbase_client = coinbase_client_module
            logging.info("✅ CoinbaseClient initialized with API keys")
        return _coinbase_client

# Trading loop control
loop_thread = None
loop_lock = threading.Lock()
stop_event = threading.Event()

app = Flask(__name__)
# expected token — store in env securely on Render
START_TOKEN = os.environ.get("START_TOKEN", "please-set-a-secret-token")

# Health endpoint (Render uses HEAD/GET)
@app.route("/health", methods=["GET", "HEAD"])
def health():
    # respond OK quickly; do not start loops here
    return ("", 200)

# Start endpoint must be POST and include token
@app.route("/start", methods=["POST", "HEAD", "GET"])
def start():
    # allow HEAD/GET for health-check compatibility, but don't start loop on HEAD/GET
    if request.method in ("HEAD", "GET"):
        # Render sometimes probes GET/HEAD -> just respond 200
        return ("", 200)

    token = request.args.get("token") or request.headers.get("X-Start-Token")
    if token != START_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    global loop_thread
    with loop_lock:
        if loop_thread is not None and loop_thread.is_alive():
            return jsonify({"status": "already_running"}), 200

        stop_event.clear()
        # start new thread
        loop_thread = threading.Thread(target=trading_loop, daemon=True)
        loop_thread.start()
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
    logging.info("🔥 Nija Ultimate AI Trading Loop Started 🔥")
    last_log = 0
    try:
        while not stop_event.is_set():
            # Fetch price (example)
            try:
                # replace with your real price fetch call
                price = client.get_price("BTC-USD") if hasattr(client, "get_price") else 30000.0
            except Exception as e:
                logging.exception("price fetch failed")
                price = None

            # throttle logs to 1/sec (or whatever you want)
            now = time.time()
            if now - last_log > 1 and price is not None:
                logging.info(f"BTC Price: {price}")
                last_log = now

            # main trading logic here...
            # add safe try/except around order placement
            time.sleep(0.5)  # tick rate, tune to your needs

    finally:
        logging.info("Trading loop exited cleanly")

# graceful shutdown for gunicorn or other envs
def _handle_term(signum, frame):
    logging.info("Received signal %s: stopping loop", signum)
    stop_event.set()
    # optionally wait a little for thread to exit
    with loop_lock:
        if loop_thread:
            loop_thread.join(timeout=5)

signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)

if __name__ == "__main__":
    # local dev only — gunicorn will run the app in production
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
