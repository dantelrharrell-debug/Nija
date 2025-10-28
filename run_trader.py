#!/usr/bin/env python3
"""
run_trader.py
Single-file dedicated trading worker for Nija.

Run as a separate container/service (recommended). Provides:
 - single-process trading loop
 - graceful shutdown on SIGTERM/SIGINT
 - tiny /health HTTP endpoint (default port 18080) for platform probes
 - idempotent Coinbase client init
 - safe logging and throttled price logs

Environment variables:
 - COINBASE_API_KEY
 - COINBASE_API_SECRET
 - LOOP_TICK            (float seconds, default 0.5)
 - PRICE_LOG_THROTTLE   (float seconds, default 1.0)
 - HEALTH_PORT          (int, default 18080)
 - DRY_RUN              (if "1", don't place real orders)
 - LOG_LEVEL            (DEBUG/INFO/WARNING, default INFO)
"""

import os
import sys
import time
import logging
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------- Configuration from env ----------
LOOP_TICK = float(os.environ.get("LOOP_TICK", "0.5"))
PRICE_LOG_THROTTLE = float(os.environ.get("PRICE_LOG_THROTTLE", "1.0"))
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "18080"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")

# ---------- Logging ----------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("nija-runner")

# ---------- Simple Health HTTP Server ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/ready"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = b'{"status":"ok"}\n'
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # avoid noisy stdout from http.server
        logger.debug("health-http %s - %s", self.client_address, format % args)

def start_health_server(stop_event, port=HEALTH_PORT):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="health-http", daemon=True)
    thread.start()
    logger.info("Health HTTP server listening on 0.0.0.0:%s (/health)", port)

    # When stop_event set -> shutdown server
    def waiter():
        stop_event.wait()
        try:
            logger.info("Shutting down health HTTP server")
            server.shutdown()
            server.server_close()
        except Exception:
            logger.exception("Error shutting down health server")

    t = threading.Thread(target=waiter, name="health-shutdown-waiter", daemon=True)
    t.start()
    return server

# ---------- Coinbase client init (idempotent per-process) ----------
_coinbase_client = None
_client_lock = threading.Lock()

def get_coinbase_client():
    """
    Try to initialize returned client in a few common ways.
    Replace or extend this function if you have a different client object.
    """
    global _coinbase_client
    with _client_lock:
        if _coinbase_client is None:
            # try your local nija_client first (common in your repo)
            try:
                from nija_client import client as coinbase_client_module
                _coinbase_client = coinbase_client_module
                logger.info("✅ CoinbaseClient initialized (nija_client module)")
                return _coinbase_client
            except Exception:
                logger.debug("nija_client import failed (ok if not present)")

            # try coinbase_advanced_py library if available
            try:
                from coinbase_advanced_py.client import CoinbaseClient
                if COINBASE_API_KEY and COINBASE_API_SECRET:
                    _coinbase_client = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
                    logger.info("✅ CoinbaseClient initialized (CoinbaseClient)")
                    return _coinbase_client
                else:
                    logger.warning("COINBASE_API_KEY/SECRET not set; CoinbaseClient not fully configured")
            except Exception:
                logger.debug("coinbase_advanced_py import failed (ok if not present)")

            # fallback stub client so you can run locally for testing
            class _StubClient:
                def get_price(self, symbol="BTC-USD"):
                    return 30000.0
                def place_order(self, *args, **kwargs):
                    raise RuntimeError("Stub: no real order")
            _coinbase_client = _StubClient()
            logger.warning("Using stub Coinbase client. Set COINBASE_API_KEY + COINBASE_API_SECRET for real client.")
        return _coinbase_client

# ---------- Trading loop ----------
stop_event = threading.Event()
loop_thread = None
loop_lock = threading.Lock()

def place_order_safe(client, order_payload):
    """
    Wrap real order placement here. This function MUST be hardened
    before going live: validate payload, handle exceptions, retries,
    and ensure idempotency where possible (client-provided order_id).
    """
    if DRY_RUN:
        logger.info("[DRY_RUN] would place order: %s", order_payload)
        return {"status": "dry-run", "payload": order_payload}
    try:
        # example: client.place_order(**order_payload)
        if hasattr(client, "place_order"):
            result = client.place_order(order_payload) if isinstance(order_payload, dict) else client.place_order(**order_payload)
            logger.info("Order placed: %s", result)
            return result
        else:
            # user-specific clients might have different method signatures
            logger.warning("Client has no place_order method; skipping")
            return None
    except Exception as e:
        logger.exception("Order placement failed: %s", e)
        # decide whether to raise (crash) or continue; here we continue
        return None

def trading_loop():
    client = get_coinbase_client()
    logger.info("🔥 Trading loop starting (pid=%s) 🔥", os.getpid())

    last_price_log_time = 0.0

    try:
        while not stop_event.is_set():
            price = None
            try:
                # Try common methods for price fetch (adapt to your client)
                if hasattr(client, "get_price"):
                    price = client.get_price("BTC-USD")
                elif hasattr(client, "get_current_price"):
                    price = client.get_current_price("BTC-USD")
                elif hasattr(client, "get_ticker"):
                    price = client.get_ticker("BTC-USD")
                else:
                    # fallback to an attribute or stub
                    price = getattr(client, "price", 30000.0)
            except Exception:
                logger.exception("Price fetch exception; continuing loop")
                price = None

            now = time.time()
            if price is not None and (now - last_price_log_time) >= PRICE_LOG_THROTTLE:
                logger.info("BTC Price: %s", price)
                last_price_log_time = now

            # =========================
            # Insert your trading strategy here.
            # Example pseudo-logic:
            # if some_signal_based_on_price_and_indicators:
            #     payload = {"product_id":"BTC-USD", "side":"buy", "size":"0.001", ...}
            #     place_order_safe(client, payload)
            # else:
            #     maybe_cancel_some_orders()
            # =========================

            time.sleep(LOOP_TICK)
    except Exception:
        logger.exception("Unexpected exception in trading loop (will exit loop)")
    finally:
        logger.info("Trading loop exiting cleanly (pid=%s)", os.getpid())

def start_trading():
    global loop_thread
    with loop_lock:
        if loop_thread is not None and loop_thread.is_alive():
            logger.warning("Trading loop already running")
            return
        loop_thread = threading.Thread(target=trading_loop, name="trading-loop", daemon=True)
        loop_thread.start()
        logger.info("Trading loop thread started")

# ---------- Signal handling (graceful shutdown) ----------
def _shutdown(signum, frame):
    logger.info("Received signal %s - initiating shutdown", signum)
    stop_event.set()
    # wait a short time for loop to exit
    with loop_lock:
        global loop_thread
        if loop_thread is not None:
            logger.info("Waiting for trading loop to exit (join with timeout)")
            loop_thread.join(timeout=10)
            if loop_thread.is_alive():
                logger.warning("Trading loop did not exit within timeout; will exit process anyway")
    # give health server a chance to close (stop_event will trigger shutdown)
    time.sleep(0.2)
    logger.info("Shutdown complete; exiting process")
    # allow process to terminate naturally

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)

# ---------- Entrypoint ----------
def main():
    logger.info("run_trader starting (pid=%s) DRY_RUN=%s", os.getpid(), DRY_RUN)

    # start health server (in background)
    start_health_server(stop_event, port=HEALTH_PORT)

    # start trading
    start_trading()

    # main thread simply waits on stop_event; keeps process alive
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received in main thread")
        stop_event.set()

    # final cleanup -- wait a tiny bit in case threads are finishing
    logger.info("run_trader main loop exiting; waiting briefly for background threads")
    time.sleep(0.5)

if __name__ == "__main__":
    main()
