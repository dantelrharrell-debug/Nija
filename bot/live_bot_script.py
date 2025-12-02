import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if API_KEY and API_SECRET:
    try:
        from coinbase_advanced_py.client import Client
        # initialize using only key & secret (no passphrase)
        client = Client(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("Coinbase client initialized. Live trading enabled.")
    except Exception as e:
        client = None
        logger.exception("Failed to initialize Coinbase client: %s", e)
else:
    client = None
    logger.warning("Coinbase client not initialized. Missing API_KEY or API_SECRET. Live trading disabled.")

# bot/live_bot_script.py
import os
import time
import threading
import logging
from typing import Optional, Dict, Any

from flask import Flask, jsonify, request

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_trading_bot")

# Coinbase credentials from env
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# Trading config (env, with defaults)
PRODUCT_ID = os.getenv("TRADE_PRODUCT_ID", "BTC-USD")      # default product
ORDER_SIZE = float(os.getenv("TRADE_ORDER_SIZE", "0.001")) # quantity (absolute) by default
TRADE_INTERVAL = float(os.getenv("TRADE_INTERVAL", "5"))   # seconds between loop iterations
MAX_ORDERS_PER_LOOP = int(os.getenv("MAX_ORDERS_PER_LOOP", "1"))
ACCOUNT_ID = os.getenv("TRADE_ACCOUNT_ID", "")             # optional, not required

# Global client variable (None if not initialized)
client = None

def initialize_coinbase_client() -> Optional[Any]:
    """
    Initialize the Coinbase client if credentials present.
    This function tries to import common client implementations robustly.
    Returns the created client or None.
    """
    global client
    if not (API_KEY and API_SECRET):
        logger.warning("No API_KEY/API_SECRET found; Coinbase client not initialized.")
        return None

    try:
        # Try coinbase_advanced_py first (your logs indicate you use this)
        from coinbase_advanced_py.client import Client as AdvancedClient
        logger.info("Initializing coinbase_advanced_py Client")
        client = AdvancedClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("coinbase_advanced_py Client initialized.")
        return client
    except Exception as e:
        logger.debug("coinbase_advanced_py import/instantiation failed: %s", e)

    try:
        # Try official coinbase client
        from coinbase.wallet.client import Client as OfficialClient
        logger.info("Initializing official coinbase Client")
        client = OfficialClient(API_KEY, API_SECRET)
        logger.info("Official coinbase Client initialized.")
        return client
    except Exception as e:
        logger.debug("official coinbase import/instantiation failed: %s", e)

    # If we reach here, no client could be created
    logger.error("Failed to initialize any Coinbase client. Live trading disabled.")
    client = None
    return None

# trading loop control
_trading_thread: Optional[threading.Thread] = None
_trading_stop_event = threading.Event()
_trading_lock = threading.Lock()
_trading_state = {"running": False, "loops": 0, "orders_placed": 0}

def _try_place_order(product_id: str, side: str, size: float, price: Optional[float] = None) -> Dict[str, Any]:
    """
    Try multiple common order-placement method signatures to support different client wrappers.
    Returns dict with status and any response or error.
    WARNING: This performs a real order when a client is initialized.
    """
    if client is None:
        raise RuntimeError("Coinbase client not initialized")

    # Prepare a generic order payload for logging
    payload = {"product_id": product_id, "side": side, "size": size, "price": price}
    logger.info("Placing order: %s", payload)

    # Try common methods and fallbacks
    method_attempts = []

    # 1) coinbase_advanced_py: try restful client patterns
    try:
        # Many wrappers expose client.create_order or client.place_order or client.rest.create_order
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
        method_attempts.append(("advanced/official attempt", str(e)))
        logger.warning("Order attempt failed on advanced/official APIs: %s", e)

    # 2) official coinbase (wallet) rarely used for spot orders on Coinbase Pro; keep for resiliency
    try:
        # some official clients use client.buy/ client.sell methods
        if hasattr(client, "buy"):
            resp = client.buy(amount=str(size), currency=product_id.split("-")[-1])
            return {"ok": True, "library": "buy", "response": resp}
        if hasattr(client, "create_transaction"):
            # wallet-style
            resp = client.create_transaction(to=product_id, amount=str(size))
            return {"ok": True, "library": "create_transaction", "response": resp}
    except Exception as e:
        method_attempts.append(("official-wallet attempt", str(e)))
        logger.warning("Order attempt failed on wallet APIs: %s", e)

    # If we can't place an order due to unknown library, raise
    error_msg = f"No supported order method found on client. Attempts: {method_attempts}"
    logger.error(error_msg)
    raise RuntimeError(error_msg)

def start_trading_loop():
    """
    Start the live trading loop in a background thread.
    Loop will respect the global _trading_stop_event to cease operation.
    """
    global _trading_thread, _trading_stop_event, _trading_state

    with _trading_lock:
        if _trading_thread and _trading_thread.is_alive():
            logger.info("Trading loop already running.")
            return

        _trading_stop_event.clear()
        _trading_state.update({"running": True, "loops": 0, "orders_placed": 0})

        def loop():
            logger.info("Trading loop starting (live mode). Product: %s; size: %s", PRODUCT_ID, ORDER_SIZE)
            while not _trading_stop_event.is_set():
                try:
                    _trading_state["loops"] += 1
                    logger.info("Loop #%d", _trading_state["loops"])

                    # Basic pre-checks
                    if client is None:
                        logger.error("Client not initialized. Stopping trading loop.")
                        break

                    # Example: place up to MAX_ORDERS_PER_LOOP market buys. (Customize logic here.)
                    orders_this_loop = 0
                    for i in range(MAX_ORDERS_PER_LOOP):
                        try:
                            result = _try_place_order(PRODUCT_ID, "buy", ORDER_SIZE)
                            logger.info("Order result: %s", result)
                            _trading_state["orders_placed"] += 1
                            orders_this_loop += 1
                        except Exception as oerr:
                            logger.error("Order failed in loop: %s", oerr)
                            # If real error (insufficient funds, etc.) break or continue depending on error
                            break

                    logger.info("Finished loop #%d: orders_placed_this_loop=%d", _trading_state["loops"], orders_this_loop)

                except Exception as ex:
                    logger.exception("Unexpected error in trading loop: %s", ex)

                # Sleep between loops (live interval)
                waited = 0.0
                while waited < TRADE_INTERVAL and not _trading_stop_event.is_set():
                    time.sleep(0.5)
                    waited += 0.5

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
        "trade_interval": TRADE_INTERVAL
    }

def create_app():
    """
    Create and return the Flask app.
    """
    # Ensure client is initialized on import/startup
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
        # Minimal order endpoint for manual trigger
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

    # Start trading automatically if env says to (optional)
    if os.getenv("AUTO_START_TRADING", "false").lower() in ("1", "true", "yes"):
        if client is not None:
            logger.info("AUTO_START_TRADING is set -> starting trading loop at startup.")
            start_trading_loop()
        else:
            logger.warning("AUTO_START_TRADING set but client not initialized; skipping auto-start.")

    return app
