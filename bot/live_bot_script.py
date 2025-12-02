# bot/live_bot_script.py (top)
# other imports...
try:
    # adjust path if your function is in live_trading.py under same package
    from .live_trading import initialize_coinbase_client, run_live_trading
    logger.info("Imported initialize_coinbase_client from .live_trading")
except Exception as e:
    # fallback: maybe it's in the same file or missing
    logger.debug("Could not import initialize_coinbase_client from .live_trading: %s", e)

# file: bot/live_bot_script.py
import os
import time
import threading
import logging
import json
from typing import Optional, Dict, Any

from flask import Flask, jsonify, request

# Logging setup (stdout + rotating file)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_trading_bot")
try:
    # optional rotating file handler
    from logging.handlers import RotatingFileHandler
    log_path = os.getenv("NIJA_TRADE_LOG_PATH", "/var/log/nija_trades.log")
    fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)
    logger.info(f"Trade logs will also be written to: {log_path}")
except Exception as e:
    logger.warning("Could not configure file logging (permission?): %s", e)

# Coinbase credentials from env
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# trading config
PRODUCT_ID = os.getenv("TRADE_PRODUCT_ID", "BTC-USD")
ORDER_SIZE = float(os.getenv("TRADE_ORDER_SIZE", "0.001"))
TRADE_INTERVAL = float(os.getenv("TRADE_INTERVAL", "5"))
MAX_ORDERS_PER_LOOP = int(os.getenv("MAX_ORDERS_PER_LOOP", "1"))

client = None

# keep a small in-memory recent trades buffer for quick API checks
_RECENT_TRADES = []
_RECENT_TRADES_MAX = int(os.getenv("RECENT_TRADES_MAX", "50"))
_RECENT_TRADES_LOCK = threading.Lock()

def _record_trade_log(entry: Dict[str, Any]):
    """Write trade record to in-memory buffer and JSON log line"""
    # ensure timestamp
    entry.setdefault("timestamp", time.time())
    # human readable block for stdout logs
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(entry["timestamp"]))
    except Exception:
        ts = str(entry["timestamp"])
    human_block = (
        "\n=== NIJA TRADE EXECUTED ===\n"
        f"Timestamp: {ts}\n"
        f"Pair: {entry.get('product_id')}\n"
        f"Side: {entry.get('side')}\n"
        f"Size: {entry.get('size')}\n"
        f"Price: {entry.get('price')}\n"
        f"Order ID: {entry.get('order_id')}\n"
        f"Library: {entry.get('library')}\n"
        "===========================\n"
    )
    logger.info(human_block)

    # structured JSON log line (one-line)
    try:
        json_line = json.dumps(entry, default=str)
        logger.info("NIJA_JSON_TRADE: %s", json_line)
    except Exception as e:
        logger.warning("Failed to JSON-serialize trade entry: %s", e)

    # keep in-memory buffer
    with _RECENT_TRADES_LOCK:
        _RECENT_TRADES.append(entry)
        if len(_RECENT_TRADES) > _RECENT_TRADES_MAX:
            _RECENT_TRADES.pop(0)

def _record_failed_order_attempt(product_id: str, side: str, size: float, error: Exception, attempts: list = None):
    attempts = attempts or []
    entry = {
        "product_id": product_id,
        "side": side,
        "size": size,
        "ok": False,
        "error": str(error),
        "attempts": attempts,
        "timestamp": time.time(),
    }
    logger.error("NIJA_ORDER_FAILED: %s", json.dumps(entry, default=str))
    with _RECENT_TRADES_LOCK:
        _RECENT_TRADES.append(entry)
        if len(_RECENT_TRADES) > _RECENT_TRADES_MAX:
            _RECENT_TRADES.pop(0)

def _try_place_order(product_id: str, side: str, size: float, price: Optional[float] = None) -> Dict[str, Any]:
    """
    Robust, multi-client order attempt. Logs and returns structured result.
    WARNING: WILL PLACE A LIVE ORDER when client is initialized.
    """
    if client is None:
        raise RuntimeError("Coinbase client not initialized")

    payload = {"product_id": product_id, "side": side, "size": size, "price": price}
    logger.info("Attempting to place live order: %s", payload)

    attempts = []
    # Try coinbase_advanced_py-like methods
    try:
        if hasattr(client, "place_order"):
            resp = client.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
            order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
            entry = {"ok": True, "library": "place_order", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size, "price": price}
            _record_trade_log(entry)
            return entry
        if hasattr(client, "create_order"):
            resp = client.create_order(product_id=product_id, side=side, size=size, price=price)
            order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
            entry = {"ok": True, "library": "create_order", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size, "price": price}
            _record_trade_log(entry)
            return entry
        if hasattr(client, "rest"):
            rest = getattr(client, "rest")
            if hasattr(rest, "place_order"):
                resp = rest.place_order(product_id=product_id, side=side, order_type="market" if price is None else "limit", size=size, price=price)
                order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
                entry = {"ok": True, "library": "rest.place_order", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size, "price": price}
                _record_trade_log(entry)
                return entry
            if hasattr(rest, "create_order"):
                resp = rest.create_order(product_id=product_id, side=side, size=size, price=price)
                order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
                entry = {"ok": True, "library": "rest.create_order", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size, "price": price}
                _record_trade_log(entry)
                return entry
    except Exception as e:
        attempts.append(("advanced attempt", str(e)))
        logger.warning("Advanced client order attempt failed: %s", e)

    # Try official wallet-style interfaces (less common for market orders)
    try:
        if hasattr(client, "buy"):
            # wallet-style buy expects amount and currency; map product to base/currency
            base_currency = product_id.split("-")[-1]
            resp = client.buy(amount=str(size), currency=base_currency)
            order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
            entry = {"ok": True, "library": "buy", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size}
            _record_trade_log(entry)
            return entry
        if hasattr(client, "create_transaction"):
            resp = client.create_transaction(to=product_id, amount=str(size))
            order_id = getattr(resp, "id", resp.get("id") if isinstance(resp, dict) else repr(resp))
            entry = {"ok": True, "library": "create_transaction", "response": resp, "order_id": order_id, "product_id": product_id, "side": side, "size": size}
            _record_trade_log(entry)
            return entry
    except Exception as e:
        attempts.append(("wallet attempt", str(e)))
        logger.warning("Wallet-style order attempt failed: %s", e)

    # No method succeeded
    err = RuntimeError("No supported order method found on client")
    _record_failed_order_attempt(product_id, side, size, err, attempts=attempts)
    raise err

# trading loop control (same variables you had)
_trading_thread: Optional[threading.Thread] = None
_trading_stop_event = threading.Event()
_trading_lock = threading.Lock()
_trading_state = {"running": False, "loops": 0, "orders_placed": 0}

def start_trading_loop():
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

                    # pre-check: client must be present
                    if client is None:
                        logger.error("Client not initialized. Stopping trading loop.")
                        break

                    # Optional: check balances BEFORE placing orders (basic)
                    try:
                        # many clients provide get_accounts() or get_account(account_id)
                        bal_info = None
                        if hasattr(client, "get_accounts"):
                            bal_info = client.get_accounts()
                            logger.debug("Balance info fetched for pre-check.")
                        elif hasattr(client, "get_account"):
                            bal_info = client.get_account()
                            logger.debug("Balance info fetched (single get_account).")
                        # You can expand balance checks here (USD available, etc.)
                    except Exception as bex:
                        logger.warning("Could not fetch balances before trading: %s", bex)

                    # place up to MAX_ORDERS_PER_LOOP market buys
                    orders_this_loop = 0
                    for i in range(MAX_ORDERS_PER_LOOP):
                        try:
                            result = _try_place_order(PRODUCT_ID, "buy", ORDER_SIZE)
                            logger.info("Order result summary: %s", {"ok": result.get("ok"), "library": result.get("library"), "order_id": result.get("order_id")})
                            _trading_state["orders_placed"] += 1
                            orders_this_loop += 1
                        except Exception as oerr:
                            logger.error("Order failed in loop: %s", oerr)
                            # If live error like insufficient funds we stop placing further orders this loop
                            break

                    logger.info("Finished loop #%d: orders_placed_this_loop=%d", _trading_state["loops"], orders_this_loop)

                except Exception as ex:
                    logger.exception("Unexpected error in trading loop: %s", ex)

                # Sleep between loops
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
    # ensure client is initialized on startup (call your existing init)
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

    @app.route("/recent_trades", methods=["GET"])
    def recent_trades():
        n = int(request.args.get("n", "20"))
        with _RECENT_TRADES_LOCK:
            recent = list(_RECENT_TRADES[-n:])
        return jsonify({"ok": True, "recent_trades": recent}), 200

    # auto-start option (optional)
    if os.getenv("AUTO_START_TRADING", "false").lower() in ("1", "true", "yes"):
        if client is not None:
            logger.info("AUTO_START_TRADING set -> starting trading loop at startup.")
            start_trading_loop()
        else:
            logger.warning("AUTO_START_TRADING set but client not initialized; skipping auto-start.")

    return app
