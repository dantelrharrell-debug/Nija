*** Begin Patch
*** Add File: nija_bot_web.py
+#!/usr/bin/env python3
+"""
+nija_bot_web.py
+Flask web entrypoint for Nija (health + control endpoints).
+
+- Health checks (GET/HEAD /health) return 200 and do NOT start trading.
+- Only POST /start?token=... or X-Start-Token header will start the trading loop.
+- POST /stop?token=... stops the loop.
+- Trading loop runs in a single background thread per process (idempotent).
+- Graceful SIGTERM handling for clean shutdown.
+"""
+import os
+import signal
+import threading
+import time
+import logging
+from flask import Flask, request, jsonify
+
+# -------- Configuration from env ----------
+PORT = int(os.environ.get("PORT", 5000))
+START_TOKEN = os.environ.get("START_TOKEN", "please-set-a-secret-token")
+PRICE_LOG_THROTTLE = float(os.environ.get("PRICE_LOG_THROTTLE", "1.0"))
+LOOP_TICK = float(os.environ.get("LOOP_TICK", "0.5"))
+
+# -------- Logging ----------
+logging.basicConfig(
+    level=logging.INFO,
+    format="%(asctime)s %(levelname)s %(threadName)s %(message)s"
+)
+logger = logging.getLogger("nija")
+
+# -------- Coinbase client (idempotent per-process) --------
+_coinbase_client = None
+_client_lock = threading.Lock()
+
+def get_coinbase_client():
+    global _coinbase_client
+    with _client_lock:
+        if _coinbase_client is None:
+            try:
+                # Try import from your local module first
+                from nija_client import client as coinbase_client_module
+                _coinbase_client = coinbase_client_module
+                logger.info("✅ CoinbaseClient initialized with API keys (module)")
+                return _coinbase_client
+            except Exception:
+                logger.debug("nija_client import failed (ok if not present)")
+
+            try:
+                from coinbase_advanced_py.client import CoinbaseClient
+                api_key = os.environ.get("COINBASE_API_KEY")
+                api_secret = os.environ.get("COINBASE_API_SECRET")
+                if api_key and api_secret:
+                    _coinbase_client = CoinbaseClient(api_key=api_key, api_secret=api_secret)
+                    logger.info("✅ CoinbaseClient initialized with API keys (CoinbaseClient)")
+                    return _coinbase_client
+                else:
+                    logger.warning("COINBASE_API_KEY/SECRET not set; CoinbaseClient not fully configured")
+            except Exception:
+                logger.debug("coinbase_advanced_py import failed (ok if not present)")
+
+            # fallback stub client
+            class _StubClient:
+                def get_price(self, symbol="BTC-USD"):
+                    return 30000.0
+            _coinbase_client = _StubClient()
+            logger.warning("Using stub Coinbase client. Set COINBASE_API_KEY + COINBASE_API_SECRET for real client.")
+        return _coinbase_client
+
+# -------- Trading loop control (per-process) --------
+loop_thread = None
+loop_lock = threading.Lock()
+stop_event = threading.Event()
+
+app = Flask(__name__)
+
+@app.route("/health", methods=["GET", "HEAD"])
+def health():
+    # Platform probes should point here; do NOT start trading logic.
+    return ("", 200)
+
+@app.route("/start", methods=["POST", "GET", "HEAD"])
+def start():
+    # If probe is HEAD/GET, do not start the loop; respond 200 for probes.
+    if request.method in ("HEAD", "GET"):
+        return ("", 200)
+
+    token = request.args.get("token") or request.headers.get("X-Start-Token")
+    if token != START_TOKEN:
+        logger.warning("Invalid start token attempt from %s", request.remote_addr)
+        return jsonify({"error": "invalid token"}), 403
+
+    global loop_thread
+    with loop_lock:
+        if loop_thread is not None and loop_thread.is_alive():
+            logger.info("Start requested but loop already running (per-process).")
+            return jsonify({"status": "already_running"}), 200
+
+        stop_event.clear()
+        loop_thread = threading.Thread(target=trading_loop, name="trading-loop", daemon=True)
+        loop_thread.start()
+        logger.info("Trading loop thread started by POST /start")
+        return jsonify({"status": "started"}), 200
+
+@app.route("/stop", methods=["POST"])
+def stop():
+    token = request.args.get("token") or request.headers.get("X-Start-Token")
+    if token != START_TOKEN:
+        return jsonify({"error": "invalid token"}), 403
+    stop_event.set()
+    return jsonify({"status": "stopping"}), 200
+
+def trading_loop():
+    client = get_coinbase_client()
+    logger.info("🔥 Nija Ultimate AI Trading Loop Started 🔥 (process %s)", os.getpid() if hasattr(os, "getpid") else "unknown")
+
+    last_price_log_time = 0.0
+    try:
+        while not stop_event.is_set():
+            price = None
+            try:
+                if hasattr(client, "get_price"):
+                    price = client.get_price("BTC-USD")
+                elif hasattr(client, "get_current_price"):
+                    price = client.get_current_price("BTC-USD")
+                else:
+                    price = getattr(client, "price", 30000.0)
+            except Exception:
+                logger.exception("Price fetch failed; continuing loop.")
+                price = None
+
+            now = time.time()
+            if price is not None and (now - last_price_log_time) >= PRICE_LOG_THROTTLE:
+                logger.info("BTC Price: %s", price)
+                last_price_log_time = now
+
+            # === Trading logic goes here (wrap order placement in try/except) ===
+            time.sleep(LOOP_TICK)
+    finally:
+        logger.info("Trading loop exited cleanly")
+
+# Graceful shutdown for SIGTERM/SIGINT (gunicorn will send SIGTERM)
+def _handle_term(signum, frame):
+    logger.info("Received signal %s, setting stop_event()", signum)
+    stop_event.set()
+    with loop_lock:
+        if loop_thread:
+            loop_thread.join(timeout=5)
+    logger.info("Shutdown handler finished for process %s", os.getpid() if hasattr(os, "getpid") else "unknown")
+
+signal.signal(signal.SIGTERM, _handle_term)
+signal.signal(signal.SIGINT, _handle_term)
+
+if __name__ == "__main__":
+    logger.info("Starting Flask dev server (for local dev only). PORT=%s", PORT)
+    app.run(host="0.0.0.0", port=PORT)
+
*** End Patch
