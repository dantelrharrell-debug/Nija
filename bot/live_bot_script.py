# bot/live_bot_script.py
import os
import time
import threading
import logging
from typing import Optional, Any, Dict

from flask import Flask, jsonify, request

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_trading_bot")

# ----------------------------
# Coinbase credentials (env)
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# ----------------------------
# Trading configuration (env-friendly)
# ----------------------------
PRODUCT_ID = os.getenv("TRADE_PRODUCT_ID", "BTC-USD")
ORDER_SIZE = float(os.getenv("TRADE_ORDER_SIZE", "0.001"))
TRADE_INTERVAL = float(os.getenv("TRADE_INTERVAL", "5"))       # seconds
MAX_ORDERS_PER_LOOP = int(os.getenv("MAX_ORDERS_PER_LOOP", "1"))
ACCOUNT_ID = os.getenv("TRADE_ACCOUNT_ID", "")                 # optional
AUTO_START = os.getenv("AUTO_START_TRADING", "false").lower() in ("1", "true", "yes")

# ----------------------------
# Global client + state
# ----------------------------
client: Optional[Any] = None

_trading_thread: Optional[threading.Thread] = None
_trading_stop_event = threading.Event()
_trading_lock = threading.Lock()
_trading_state = {"running": False, "loops": 0, "orders_placed": 0}

# ----------------------------
# Coinbase init function (paste you gave)
# ----------------------------
def initialize_coinbase_client() -> Optional[Any]:
    """
    Initialize Coinbase client using ONLY API_KEY and API_SECRET.
    No passphrase required. No simulation. Fully live trading.
    """
    global client

    # Require ONLY key + secret
    if not (API_KEY and API_SECRET):
        logger.warning("Missing COINBASE_API_KEY or COINBASE_API_SECRET. Live trading disabled.")
        client = None
        return None

    # Try coinbase_advanced_py first
    try:
        from coinbase_advanced_py.client import Client as AdvancedClient
        logger.info("coinbase_advanced_py detected. Initializing advanced client...")
        client = AdvancedClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("Advanced Coinbase client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except ModuleNotFoundError:
        # Not installed — that's fine; we'll fallback.
        logger.info("coinbase_advanced_py not installed; will try official coinbase client.")
    except Exception as e:
        logger.warning(f"coinbase_advanced_py failed: {e}. Falling back to official client...")

    # Fallback → official coinbase client
    try:
        from coinbase.wallet.client import Client as WalletClient
        logger.info("Initializing official Coinbase (wallet) client...")
        client = WalletClient(API_KEY, API_SECRET)
        logger.info("Official coinbase Client initialized successfully. LIVE TRADING ENABLED.")
        return client
    except ModuleNotFoundError:
        logger.info("Official 'coinbase' package not installed; no fallback available.")
    except Exception as e:
        logger.error(f"Official coinbase client init failed: {e}")

    client = None
    logger.error("Could NOT initialize ANY Coinbase client. LIVE TRADING DISABLED.")
    return None

# ----------------------------
# Order attempt helper (robust cross-client)
# ----------------------------
def _try_place_order(product_id: str, side: str, size: float, price: Optional[float] = None) -> Dict[str, Any]:
    """
    Attempt to place an order using common client method names.
    This performs a REAL order if client is initialized.
    Returns dict with result or raises on unrecoverable failure.
    """
    if client is None:
        raise RuntimeError("Coinbase client not initialized")

    payload = {"product_id": product_id, "side": side, "size": size, "price": price}
    logger.info("Placing order: %s", payload)

    attempts = []

    # 1) coinbase_advanced_py style / pro-style
    try:
        # some wrappers expose place_order/create_order at top level
        if hasattr(client, "place_order"):
            resp = client.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
            return {"ok": True, "library": "place_order", "response": resp}
        if hasattr(client, "create_order"):
            resp = client.create_order(product_id=product_id, side=side, size=size, price=price)
            return {"ok": True, "library": "create_order", "response": resp}
        # nested rest property
        if hasattr(client, "rest"):
            rest = getattr(client, "rest")
            if hasattr(rest, "place_order"):
                resp = rest.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
                return {"ok": True, "library": "rest.place_order", "response": resp}
            if hasattr(rest, "create_order"):
                resp = rest.create_order(product_id=product_id, side=side, size=size, price=price)
                return {"ok": True, "library": "rest.create_order", "response": resp}
    except Exception as e:
        attempts.append(("advanced attempt", str(e)))
        logger.warning("Order attempt failed on advanced API: %s", e)

    # 2) official wallet-style client
    try:
        if hasattr(client, "buy"):
            # wallet.buy often expects amount + currency
            amount = str(size)
            currency = product_id.split("-")[-1] if "-" in product_id else product_id
            resp = client.buy(amount=amount, currency=currency)
            return {"ok": True, "library": "buy", "response": resp}
        if hasattr(client, "create_transaction"):
            # wallet-style transaction (less common for direct orders)
            resp = client.create_transaction(to=product_id, amount=str(size))
            return {"ok": True, "library": "create_transaction", "response": resp}
    except Exception as e:
        attempts.append(("wallet attempt", str(e)))
        logger.warning("Order attempt failed on wallet API: %s", e)

    error_msg = f"No supported order method found on client. Attempts: {attempts}"
    logger.error(error_msg)
    raise RuntimeError(error_msg)

# ----------------------------
# Trading loop management
# ----------------------------
def start_trading_loop():
    global _trading_thread, _trading_stop_event, _trading_state

    with _trading_lock:
        if _trading_thread and _trading_thread.is_alive():
            logger.info("Trading loop already running.")
            return

        _trading_stop_event.clear()
        _trading_state.update({"running": True, "loops": 0, "orders_placed": 0})

        def loop():
            logger.info("Trading loop starting (LIVE). Product=%s size=%s", PRODUCT_ID, ORDER_SIZE)
            while not _trading_stop_event.is_set():
                try:
                    _trading_state["loops"] += 1
                    loop_index = _trading_state["loops"]
                    logger.info("Loop #%d", loop_index)

                    if client is None:
                        logger.error("Client not initialized. Stopping trading loop.")
                        break

                    orders_this_loop = 0
                    for i in range(MAX_ORDERS_PER_LOOP):
                        try:
                            result = _try_place_order(PRODUCT_ID, "buy", ORDER_SIZE)
                            logger.info("Order result: %s", result)
                            _trading_state["orders_placed"] += 1
                            orders_this_loop += 1
                        except Exception as order_err:
                            logger.error("Order failed in loop: %s", order_err)
                            # decide whether to continue or break; here we break to avoid repeated failures
                            break

                    logger.info("Finished loop #%d: orders_placed_this_loop=%d", loop_index, orders_this_loop)

                except Exception as ex:
                    logger.exception("Unexpected error in trading loop: %s", ex)

                # sleep in small increments to be responsive to stop event
                slept = 0.0
                while slept < TRADE_INTERVAL and not _trading_stop_event.is_set():
                    time.sleep(0.5)
                    slept += 0.5

            logger.info("Trading loop stopping.")
            _trading_state["running"] = False

        _trading_thread = threading.Thread(target=loop, daemon=True, name="live-trading-loop")
        _trading_thread.start()
        logger.info("Trading thread started.")

def stop_trading_loop():
    global _trading_thread, _trading_stop_event
    _trading_stop_event.set()
    if _trading_thread:
        _trading_thread.join(timeout=10)
    logger.info("Trading loop stopped.")

def status_info():
    return {
        "running": _trading_state.get("running", False),
        "loops": _trading_state.get("loops", 0),
        "orders_placed": _trading_state.get("orders_placed", 0),
        "product_id": PRODUCT_ID,
        "order_size": ORDER_SIZE,
        "trade_interval": TRADE_INTERVAL,
        "client_initialized": client is not None
    }

# ----------------------------
# Flask app factory
# ----------------------------
def create_app():
    # Initialize Coinbase client at startup (safe: initialize handles missing libs)
    initialize_coinbase_client()

    app = Flask("nija_live_bot")

    @app.route("/__health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "client_initialized": client is not None}), 200

    @app.route("/status", methods=["GET"])
    def status():
        return jsonify(status_info()), 200

    @app.route("/start", methods=["POST"])
    def start():
        if client is None:
            return jsonify({"ok": False, "error": "Coinbase client not initialized; cannot start trading."}), 400
        start_trading_loop()
        return jsonify({"ok": True, "started": True}), 200

    @app.route("/stop", methods=["POST"])
    def stop():
        stop_trading_loop()
        return jsonify({"ok": True, "stopped": True}), 200

    @app.route("/place_order", methods=["POST"])
    def place_order_endpoint():
        data = request.json or {}
        product = data.get("product_id", PRODUCT_ID)
        side = data.get("side", "buy")
        size = float(data.get("size", ORDER_SIZE))
        price = data.get("price")
        try:
            resp = _try_place_order(product, side, size, price)
            return jsonify({"ok": True, "resp": str(resp)}), 200
        except Exception as e:
            logger.exception("place_order error")
            return jsonify({"ok": False, "error": str(e)}), 500

    # Auto-start trading if requested and client initialized
    if AUTO_START:
        if client is not None:
            logger.info("AUTO_START_TRADING enabled -> starting trading loop at startup.")
            start_trading_loop()
        else:
            logger.warning("AUTO_START_TRADING set but client not initialized; skipping auto-start.")

    return app

# ----------------------------
# Module-level WSGI app for Gunicorn: import create_app from web.wsgi or top-level web.wsgi should expect web.wsgi:app
# If you are using a separate web/wsgi.py that imports this module, it should call create_app()
# ----------------------------
# optional convenience: if module imported directly, create app
try:
    # If gunicorn imports `from bot.live_bot_script import create_app`, this will exist.
    # Do not auto-start trading here; create_app handles initialization and possible auto-start.
    pass
except Exception:
    logger.exception("Unexpected error during module import.")

if __name__ == "__main__":
    # For local dev only — don't run the live thread automatically unless AUTO_START is set inside create_app.
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
