# bot/live_bot_script.py
import os
import time
import threading
import logging
from typing import Optional, Any, Dict

from flask import Flask, jsonify, request, abort

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_trading_bot")

# ----------------------------
# Coinbase credentials & config
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# Trading config (env, with sensible defaults)
PRODUCT_ID = os.getenv("TRADE_PRODUCT_ID", "BTC-USD")
ORDER_SIZE = float(os.getenv("TRADE_ORDER_SIZE", "0.001"))
TRADE_INTERVAL = float(os.getenv("TRADE_INTERVAL", "5"))   # seconds between loop iterations
MAX_ORDERS_PER_LOOP = int(os.getenv("MAX_ORDERS_PER_LOOP", "1"))

# Admin protection (optional)
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")  # if set, endpoints require this header: Authorization: Bearer <ADMIN_SECRET>

# Safety toggles
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")
AUTO_START_TRADING = os.getenv("AUTO_START_TRADING", "false").lower() in ("1", "true", "yes")

# Global client variable
client: Optional[Any] = None

# Trading loop control
_trading_thread: Optional[threading.Thread] = None
_trading_stop_event = threading.Event()
_trading_lock = threading.Lock()
_trading_state = {"running": False, "loops": 0, "orders_placed": 0}


def initialize_coinbase_client() -> Optional[Any]:
    """
    Robust client init:
     - Prefer coinbase_advanced_py (if installed)
     - Fallback to official 'coinbase' package
     - Do NOT require a passphrase here (support key+secret only)
    """
    global client
    if not (API_KEY and API_SECRET):
        logger.warning("No COINBASE_API_KEY/COINBASE_API_SECRET found; Coinbase client not initialized.")
        client = None
        return None

    # Try advanced/pro client first (if you want Pro functionality)
    try:
        from coinbase_advanced_py.client import Client as AdvancedClient  # optional package
        logger.info("Found coinbase_advanced_py; initializing advanced client.")
        client = AdvancedClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("coinbase_advanced_py Client initialized.")
        return client
    except ModuleNotFoundError:
        logger.info("coinbase_advanced_py not installed; will try official coinbase client.")
    except Exception as e:
        logger.warning("coinbase_advanced_py import/instantiation failed: %s", e)

    # Fallback -> official wallet client
    try:
        from coinbase.wallet.client import Client as WalletClient
        logger.info("Initializing official coinbase wallet Client (fallback).")
        client = WalletClient(API_KEY, API_SECRET)
        logger.info("Official coinbase Client initialized (fallback).")
        return client
    except Exception as e:
        logger.error("Official coinbase client init failed: %s", e)

    client = None
    logger.error("Failed to initialize any Coinbase client. Live trading disabled.")
    return None


def _try_place_order(product_id: str, side: str, size: float, price: Optional[float] = None) -> Dict[str, Any]:
    """
    Try multiple common order-placement method signatures to support different client wrappers.
    Returns dict with status and any response or error.
    WARNING: This performs a real order when a client is initialized and DRY_RUN=False.
    """
    if client is None:
        raise RuntimeError("Coinbase client not initialized")

    payload = {"product_id": product_id, "side": side, "size": size, "price": price}
    logger.info("Attempting to place order: %s", payload)

    # If DRY_RUN is set, don't send a live order
    if DRY_RUN:
        logger.info("DRY_RUN enabled — not placing live order. Pretending success.")
        return {"ok": True, "library": "dry-run", "response": {"payload": payload, "note": "dry-run"}}

    # Track attempts and errors for diagnostics
    attempts = []

    # 1) coinbase_advanced_py style / REST-style clients
    try:
        # common top-level methods
        if hasattr(client, "place_order"):
            resp = client.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
            return {"ok": True, "library": "place_order", "response": resp}
        if hasattr(client, "create_order"):
            resp = client.create_order(product_id=product_id, side=side, size=size, price=price, order_type="market" if price is None else "limit")
            return {"ok": True, "library": "create_order", "response": resp}

        # nested client.rest.* patterns
        if hasattr(client, "rest"):
            rest = getattr(client, "rest")
            if hasattr(rest, "place_order"):
                resp = rest.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
                return {"ok": True, "library": "rest.place_order", "response": resp}
            if hasattr(rest, "create_order"):
                resp = rest.create_order(product_id=product_id, side=side, size=size, price=price)
                return {"ok": True, "library": "rest.create_order", "response": resp}
    except Exception as e:
        attempts.append(("advanced/pro attempt", str(e)))
        logger.warning("Order attempt failed on advanced/pro APIs: %s", e)

    # 2) Official wallet-style client (limited capabilities)
    try:
        # Official wallet client often provides buy/sell transactions; amounts are currency/fiat oriented.
        if hasattr(client, "buy"):
            # official buy expects amount & currency; adapt by using quote currency from product_id
            quote_currency = product_id.split("-")[-1]
            resp = client.buy(amount=str(size), currency=quote_currency)
            return {"ok": True, "library": "buy", "response": resp}
        if hasattr(client, "create_transaction"):
            resp = client.create_transaction(to=product_id, amount=str(size))
            return {"ok": True, "library": "create_transaction", "response": resp}
    except Exception as e:
        attempts.append(("official-wallet attempt", str(e)))
        logger.warning("Order attempt failed on wallet APIs: %s", e)

    # If we couldn't find a method to place an order, raise with diagnostics
    error_msg = f"No supported order method found on client. Attempts: {attempts}"
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

                    orders_this_loop = 0
                    for i in range(MAX_ORDERS_PER_LOOP):
                        try:
                            result = _try_place_order(PRODUCT_ID, "buy", ORDER_SIZE)
                            logger.info("Order result: %s", result)
                            _trading_state["orders_placed"] += 1
                            orders_this_loop += 1
                        except Exception as oerr:
                            logger.error("Order failed in loop: %s", oerr)
                            # Break current loop on an error that likely won't succeed repeatedly
                            break

                    logger.info("Finished loop #%d: orders_placed_this_loop=%d", _trading_state["loops"], orders_this_loop)

                except Exception as ex:
                    logger.exception("Unexpected error in trading loop: %s", ex)

                # Sleep between loops (live interval), but remain responsive to stop event
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
        "trade_interval": TRADE_INTERVAL,
        "client_initialized": client is not None,
        "dry_run": DRY_RUN,
    }


def _require_admin(req: request) -> bool:
    """
    If ADMIN_SECRET is set, require Authorization header: Bearer <ADMIN_SECRET>
    """
    if not ADMIN_SECRET:
        return True
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    return token == ADMIN_SECRET


def create_app():
    """
    Create and return the Flask app.
    """
    # Initialize client at import/startup
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
        if not _require_admin(request):
            abort(401)
        if client is None:
            return jsonify({"ok": False, "error": "Coinbase client not initialized; cannot start trading."}), 400
        start_trading_loop()
        return jsonify({"ok": True, "started": True}), 200

    @app.route("/stop", methods=["POST"])
    def stop():
        if not _require_admin(request):
            abort(401)
        stop_trading_loop()
        return jsonify({"ok": True, "stopped": True}), 200

    @app.route("/place_order", methods=["POST"])
    def place_order_endpoint():
        if not _require_admin(request):
            abort(401)
        data = request.json or {}
        product = data.get("product_id", PRODUCT_ID)
        side = data.get("side", "buy")
        size = float(data.get("size", ORDER_SIZE))
        price = data.get("price")
        try:
            resp = _try_place_order(product, side, size, price)
            return jsonify({"ok": True, "resp": resp}), 200
        except Exception as e:
            logger.exception("place_order error")
            return jsonify({"ok": False, "error": str(e)}), 500

    # Optionally auto-start trading if requested and client exists
    if AUTO_START_TRADING:
        if client is not None:
            logger.info("AUTO_START_TRADING is set -> starting trading loop at startup.")
            start_trading_loop()
        else:
            logger.warning("AUTO_START_TRADING set but client not initialized; skipping auto-start.")

    return app


# If this module is executed directly, run a dev server (not for production)
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
