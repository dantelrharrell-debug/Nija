from nija_hmac_client import CoinbaseClient

client = CoinbaseClient()
status, accounts = client.get_accounts()
if status != 200:
    raise Exception(f"Failed to fetch accounts: {accounts}")

print(accounts)

run_trader.py

# --- Existing trading logic below ---
# Your trading loop can now safely use `accounts`
while True:
    # Example: check balances or open positions
    print("Checking balances...")
    time.sleep(60)

#!/usr/bin/env python3
"""
run_trader.py
Single-file dedicated trading worker for Nija.

Features in this version:
- Binds health HTTP server to the platform-provided $PORT when present,
  otherwise falls back to HEALTH_PORT env or 18080.
- Single-process trading loop with graceful shutdown on SIGTERM/SIGINT.
- Idempotent Coinbase client init with stub fallback.
- Price logging: INFO level while DRY_RUN=1 (easy debugging). In live mode
  price logs are emitted at DEBUG to avoid flooding INFO logs; change LOG_LEVEL
  env to DEBUG if you want them visible.
- Environment-driven config; no terminal required for deploy edits.
"""

import os
import sys
import time
import logging
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------- Configuration from env ----------
# Trading loop tick (seconds)
LOOP_TICK = float(os.environ.get("LOOP_TICK", "0.5"))

# How often to log the price (seconds)
PRICE_LOG_THROTTLE = float(os.environ.get("PRICE_LOG_THROTTLE", "1.0"))

# Prefer platform-provided PORT (e.g. Render/Railway) for health binding.
# If not present, fallback to HEALTH_PORT env var or 18080.
HEALTH_PORT = int(os.environ.get("PORT") or os.environ.get("HEALTH_PORT", "18080"))

# Dry-run mode: do not place real orders
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

# Logging level: INFO by default (so DEBUG price logs are hidden in live)
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
            self.wfile.write(b'{"status":"ok"}\n')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # suppress default noisy stdout; route to logger at debug level
        logger.debug("health-http %s - %s", self.client_address, format % args)

def start_health_server(stop_event, port=HEALTH_PORT):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
    except Exception as e:
        logger.exception("Failed to bind health server to port %s: %s", port, e)
        raise

    thread = threading.Thread(target=server.serve_forever, name="health-http", daemon=True)
    thread.start()
    logger.info("Health HTTP server listening on 0.0.0.0:%s (/health)", port)

    # Stop server when stop_event set
    def waiter():
        stop_event.wait()
        try:
            logger.info("Shutting down health HTTP server")
            server.shutdown()
            server.server_close()
        except Exception:
            logger.exception("Error shutting down health server.")

    t = threading.Thread(target=waiter, name="health-shutdown-waiter", daemon=True)
    t.start()
    return server

# ---------- Coinbase client init (idempotent per-process) ----------
_coinbase_client = None
_client_lock = threading.Lock()

def get_coinbase_client():
    """
    Initialize and return a client object. Tries common options, falls back to a stub.
    Replace or extend for your real client object.
    """
    global _coinbase_client
    with _client_lock:
        if _coinbase_client is None:
            # Try local nija_client module first
            try:
                from nija_client import client as coinbase_client_module
                _coinbase_client = coinbase_client_module
                logger.info("✅ CoinbaseClient initialized (nija_client module)")
                return _coinbase_client
            except Exception:
                logger.debug("nija_client import not available")

            # Try coinbase_advanced_py client class
            try:
                
                if COINBASE_API_KEY and COINBASE_API_SECRET:
                    _coinbase_client = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
                    logger.info("✅ CoinbaseClient initialized (CoinbaseClient)")
                    return _coinbase_client
                else:
                    logger.warning("COINBASE_API_KEY/SECRET not set; CoinbaseClient not configured")
            except Exception:
                logger.debug("coinbase_advanced_py import failed (not present)")

            # Fallback stub client so the service can run without real keys
            class _StubClient:
                def get_price(self, symbol="BTC-USD"):
                    return 30000.0
                def place_order(self, *args, **kwargs):
                    raise RuntimeError("Stub client: no real orders")
            _coinbase_client = _StubClient()
            logger.warning("Using stub Coinbase client. Set COINBASE_API_KEY + COINBASE_API_SECRET for real trading.")
        return _coinbase_client

# ---------- Trading loop ----------
stop_event = threading.Event()
loop_thread = None
loop_lock = threading.Lock()

def place_order_safe(client, order_payload):
    """
    Wrap order placement; ensure idempotency, validation, and exception handling
    before turning live. This is intentionally conservative.
    """
    if DRY_RUN:
        logger.info("[DRY_RUN] would place order: %s", order_payload)
        return {"status": "dry-run", "payload": order_payload}

    try:
        # Adapt this to your client's API
        if hasattr(client, "place_order"):
            if isinstance(order_payload, dict):
                return client.place_order(**order_payload)
            else:
                return client.place_order(order_payload)
        else:
            logger.warning("Client has no place_order method; skipping actual placement.")
            return None
    except Exception:
        logger.exception("Order placement failed")
        return None

def trading_loop():
    client = get_coinbase_client()
    logger.info("🔥 Trading loop starting (pid=%s) 🔥", os.getpid() if hasattr(os, "getpid") else "unknown")

    last_price_log_time = 0.0

    try:
        while not stop_event.is_set():
            price = None
            try:
                if hasattr(client, "get_price"):
                    price = client.get_price("BTC-USD")
                elif hasattr(client, "get_current_price"):
                    price = client.get_current_price("BTC-USD")
                elif hasattr(client, "get_ticker"):
                    price = client.get_ticker("BTC-USD")
                else:
                    price = getattr(client, "price", 30000.0)
            except Exception:
                logger.exception("Price fetch exception; continuing loop")
                price = None

            now = time.time()
            if price is not None and (now - last_price_log_time) >= PRICE_LOG_THROTTLE:
                # Logging policy:
                # - In DRY_RUN we keep price logs at INFO so tests are visible.
                # - In live (DRY_RUN=False) we log price at DEBUG to avoid spamming INFO-level logs.
                if DRY_RUN:
                    logger.info("BTC Price: %s", price)
                else:
                    logger.debug("BTC Price: %s", price)
                last_price_log_time = now

            # ===== Insert trading strategy here =====
            # Example placeholder:
            # if some_signal(price):
            #     payload = {"product_id":"BTC-USD","side":"buy","size":"0.001"}
            #     place_order_safe(client, payload)

            time.sleep(LOOP_TICK)
    except Exception:
        logger.exception("Unexpected exception in trading loop (will exit)")
    finally:
        logger.info("Trading loop exiting cleanly (pid=%s)", os.getpid() if hasattr(os, "getpid") else "unknown")

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
    with loop_lock:
        global loop_thread
        if loop_thread is not None:
            logger.info("Waiting for trading loop to exit (join with timeout)")
            loop_thread.join(timeout=10)
            if loop_thread.is_alive():
                logger.warning("Trading loop did not exit within timeout; forcing shutdown")
    # Let main process exit naturally
    logger.info("Shutdown sequence finished for pid=%s", os.getpid() if hasattr(os, "getpid") else "unknown")

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)

# ---------- Entrypoint ----------
def main():
    logger.info("run_trader starting (pid=%s) DRY_RUN=%s LOG_LEVEL=%s HEALTH_PORT=%s",
                os.getpid() if hasattr(os, "getpid") else "unknown", DRY_RUN, LOG_LEVEL, HEALTH_PORT)

    # Start health server first (binds to platform $PORT when present)
    start_health_server(stop_event, port=HEALTH_PORT)

    # Start trading loop
    start_trading()

    # Keep the main thread alive while background threads run
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received in main thread; initiating shutdown")
        stop_event.set()

    logger.info("run_trader main loop exiting; final cleanup")
    time.sleep(0.2)

if __name__ == "__main__":
    main()
