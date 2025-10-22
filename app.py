# nija_bot_web/app.py
"""
Nija - unified Flask app (paste-ready).
Includes:
 - safe Coinbase client attachment from env
 - defensive place_order() + fetch_account_balance()
 - bot_loop() with auto-scaling + VWAP/RSI signals
 - Flask routes: /dashboard, /dashboard/data, /health, /start, /stop
 - Debug endpoints: /_debug/ping, /_debug/client, /_debug/test_order
"""

import os
import time
import logging
from threading import Thread
from flask import Flask, render_template, jsonify, request

# Import your local modules (ensure these exist in the project)
# config.py should define SPOT_TICKERS and FUTURES_TICKERS lists.
# position_manager.py should define get_trade_allocation(account_balance, desired_percent=0.05)
# trading_logic.py should define generate_signal(symbol, client=None, granularity_seconds=60, lookback=100, rsi_period=14)
from config import SPOT_TICKERS, FUTURES_TICKERS
from position_manager import get_trade_allocation
from trading_logic import generate_signal

# === Logging ===
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.app")

# === Flask app ===
app = Flask(__name__)

# -----------------------------------------------------------------------------
# Coinbase client attachment (env-driven, defensive)
# -----------------------------------------------------------------------------
CLIENT = None
try:
    from coinbase_advanced_py.client import CoinbaseClient as CoinbaseAdvancedClient
except Exception:
    CoinbaseAdvancedClient = None

def attach_coinbase_client_from_env():
    api_key = os.getenv("COINBASE_KEY") or os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_SECRET") or os.getenv("COINBASE_API_SECRET")
    api_pass = os.getenv("COINBASE_PASSPHRASE")  # optional
    if not api_key or not api_secret:
        _logger.info("Coinbase keys missing in env -> running in simulation mode (client None).")
        return None

    if CoinbaseAdvancedClient is not None:
        try:
            _logger.info("Instantiating coinbase_advanced_py CoinbaseClient from env vars.")
            client = CoinbaseAdvancedClient(api_key=api_key, api_secret=api_secret)
            _logger.info("Coinbase client instantiated (coinbase_advanced_py).")
            return client
        except Exception as e:
            _logger.exception("Failed to instantiate coinbase_advanced_py client: %s", e)

    _logger.warning("No compatible Coinbase client available or instantiation failed. Simulation mode active.")
    return None

# Attach at import time (safe)
client = attach_coinbase_client_from_env()
CLIENT = client  # alternate name if other modules import

# -----------------------------------------------------------------------------
# Defensive order & balance helpers (can be replaced with nija_orders.py if preferred)
# -----------------------------------------------------------------------------
_last_balance_fetch_ts = 0
_balance_cache_ttl = 30  # seconds between live balance fetches

def place_order(symbol, market_type, side, amount):
    """
    Defensive order placement. Returns dict: {"status":"ok"/"simulated"/"error", "order":...}
    - symbol e.g. "BTC/USD"
    - market_type: "Spot" or "Futures" (for informational use)
    - side: "buy" or "sell"
    - amount: USD amount or size depending on client expectations (adapt if needed)
    """
    _logger.info("place_order called -> symbol=%s, type=%s, side=%s, amount=%s, client_attached=%s",
                 symbol, market_type, side, amount, client is not None)
    if client is None:
        _logger.info("place_order: client is None -> simulated order returned")
        return {"status": "simulated", "order": {"symbol": symbol, "side": side, "amount": amount}}

    product_id_dash = symbol.replace("/", "-")
    # Candidate client methods to try
    candidate_methods = [
        ("place_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("create_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("submit_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
    ]

    for fn_name, kwargs in candidate_methods:
        fn = getattr(client, fn_name, None)
        if callable(fn):
            try:
                _logger.info("Attempting client.%s with args %s", fn_name, kwargs)
                order = fn(**kwargs)
                _logger.info("place_order: client.%s success -> %s", fn_name, order)
                return {"status": "ok", "order": order}
            except TypeError:
                try:
                    order = fn(kwargs.get("product_id"), kwargs.get("side"), kwargs.get("size"))
                    _logger.info("place_order: client.%s (positional) success -> %s", fn_name, order)
                    return {"status": "ok", "order": order}
                except Exception as e:
                    _logger.exception("place_order: client.%s positional failed: %s", fn_name, e)
                    continue
            except Exception as e:
                _logger.exception("place_order: client.%s error: %s", fn_name, e)
                continue

    _logger.error("place_order: no known order method succeeded on client.")
    return {"status": "error", "error": "no_known_order_method_on_client"}

def fetch_account_balance(client_obj, default_currency='USD'):
    """
    Defensive fetch of total USD account balance. Returns float USD or None if can't fetch.
    Uses TTL to prevent frequent calls.
    """
    global _last_balance_fetch_ts
    now = time.time()
    if now - _last_balance_fetch_ts < _balance_cache_ttl:
        return None
    if client_obj is None:
        _logger.info("fetch_account_balance: client is None -> skipping live fetch")
        return None

    try:
        accounts = None
        for fn in ("get_accounts", "list_accounts", "get_all_accounts", "accounts"):
            meth = getattr(client_obj, fn, None)
            if callable(meth):
                try:
                    accounts = meth()
                    break
                except Exception as e:
                    _logger.debug("fetch_account_balance: client.%s raised %s", fn, e)
                    continue
            if meth is not None:
                accounts = meth
                break

        if not accounts:
            _logger.warning("fetch_account_balance: no accounts-like response from client.")
            return None

        # Normalize accounts structure
        if isinstance(accounts, dict) and "data" in accounts and isinstance(accounts["data"], list):
            accounts = accounts["data"]

        total_usd = 0.0
        for acc in accounts:
            try:
                if isinstance(acc, dict):
                    bal = acc.get("balance") or acc.get("available") or acc.get("amount")
                    if isinstance(bal, dict) and "amount" in bal and "currency" in bal:
                        amount = float(bal["amount"])
                        currency = bal["currency"].upper()
                    else:
                        amount = float(bal)
                        currency = acc.get("currency", default_currency).upper()
                else:
                    bal_obj = getattr(acc, "balance", None) or getattr(acc, "amount", None)
                    if bal_obj is not None and hasattr(bal_obj, "amount"):
                        amount = float(getattr(bal_obj, "amount"))
                        currency = getattr(bal_obj, "currency", default_currency).upper()
                    else:
                        continue

                if currency in ("USD", "USDC", "USDT", "DAI"):
                    total_usd += amount
                    continue

                # get spot price for conversion
                price = None
                for price_fn_name in ("get_spot_price", "get_price", "get_ticker", "get_product_ticker", "ticker"):
                    pf = getattr(client_obj, price_fn_name, None)
                    if callable(pf):
                        try:
                            product = f"{currency}-USD"
                            out = None
                            try:
                                out = pf(product_id=product)
                            except TypeError:
                                out = pf(product)
                            if isinstance(out, dict):
                                price_val = out.get("price") or out.get("amount") or out.get("last")
                                if price_val:
                                    price = float(price_val)
                                    break
                            else:
                                if hasattr(out, "price"):
                                    price = float(out.price)
                                    break
                                if isinstance(out, (list, tuple)) and len(out) > 0:
                                    price = float(out[0])
                                    break
                        except Exception:
                            continue

                if price is None:
                    _logger.warning("fetch_account_balance: couldn't get price for %s, skipping conversion", currency)
                    continue
                total_usd += amount * price
            except Exception as e:
                _logger.exception("fetch_account_balance: error parsing account entry: %s", e)
                continue

        _last_balance_fetch_ts = now
        return round(total_usd, 2)
    except Exception as e:
        _logger.exception("fetch_account_balance top-level error: %s", e)
        return None

# -----------------------------------------------------------------------------
# Bot globals & helpers
# -----------------------------------------------------------------------------
running = True
account_balance = float(os.getenv("STARTING_BALANCE", "15.0"))
positions = []  # list of dicts: symbol,type,side,size,entry,pl
signals = []    # list of last signals

def upsert_position(symbol, market_type, side, size, entry):
    existing = next((p for p in positions if p['symbol']==symbol and p['type']==market_type), None)
    if existing:
        existing.update({"side": side, "size": size, "entry": entry})
    else:
        positions.append({
            "symbol": symbol,
            "type": market_type,
            "side": side,
            "size": size,
            "entry": entry,
            "pl": 0.0
        })

def update_positions_and_signals():
    """
    Uses trading_logic.generate_signal to compute signals per symbol and upserts positions.
    """
    global positions, signals, account_balance
    signals = []
    for market_type, tickers in [("Spot", SPOT_TICKERS), ("Futures", FUTURES_TICKERS)]:
        for symbol in tickers:
            try:
                sig = generate_signal(symbol, client=client)
                sig['type'] = market_type
            except Exception as e:
                _logger.exception("generate_signal error for %s: %s", symbol, e)
                sig = {"symbol": symbol, "signal": "HOLD", "reason": f"error:{e}", "rsi": None, "vwap": None, "price": None, "type": market_type}

            signals.append(sig)

            if sig.get('signal') in ("LONG", "SHORT"):
                amt = get_trade_allocation(account_balance)
                # map LONG/SHORT to buy/sell for place_order
                side = "buy" if sig.get('signal') == "LONG" else "sell"
                order_result = place_order(symbol, market_type, side, amt)
                entry_price = sig.get('price') or 0.0
                upsert_position(symbol, market_type, sig.get('signal'), amt, entry_price)
            else:
                # HOLD -> keep existing positions unchanged
                pass

# -----------------------------------------------------------------------------
# Main bot loop (paste-ready, with live balance refresh)
# -----------------------------------------------------------------------------
def bot_loop():
    """
    Main trading loop for Nija:
     - periodically refreshes live balance via fetch_account_balance()
     - updates signals & positions
     - safe simulation if client not attached
    """
    global account_balance, running
    _logger.info("🚀 Nija live trading loop started...")
    while running:
        try:
            bal = fetch_account_balance(client)
            if bal is not None:
                account_balance = bal
                _logger.info("💰 Live Coinbase balance updated: $%s", account_balance)
            update_positions_and_signals()
        except Exception as e:
            _logger.exception("Bot loop error: %s", e)
        time.sleep(2)

# Start bot loop in background thread (daemon)
try:
    Thread(target=bot_loop, daemon=True).start()
except Exception as e:
    _logger.exception("Failed to start bot loop thread: %s", e)

# -----------------------------------------------------------------------------
# Flask routes
# -----------------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/dashboard/data")
def dashboard_data():
    return jsonify({
        "status": "live" if running else "stopped",
        "account_balance": account_balance,
        "positions": positions,
        "signals": signals
    })

@app.route("/health")
def health_check():
    return jsonify({
        "status": "Flask alive",
        "trading": "live" if running else "stopped",
        "coinbase": "reachable" if client is not None else "client_not_attached"
    })

@app.route("/start", methods=["POST"])
def start_trading():
    global running
    if not running:
        running = True
        Thread(target=bot_loop, daemon=True).start()
    return jsonify({"status": "Nija started", "mode": "live"})

@app.route("/stop", methods=["POST"])
def stop_trading():
    global running
    running = False
    return jsonify({"status": "Nija stopped"})

# -----------------------------------------------------------------------------
# Temporary debug endpoints (safe, remove after debugging)
# -----------------------------------------------------------------------------
@app.route("/_debug/ping")
def _debug_ping():
    return jsonify({"pong": True, "ts": time.time()})

@app.route("/_debug/client")
def _debug_client():
    try:
        client_repr = repr(client) if client is not None else None
    except Exception:
        client_repr = str(type(client))
    return jsonify({"client_attached": client is not None, "client_repr": client_repr})

@app.route("/_debug/test_order", methods=["POST"])
def _debug_test_order():
    """
    Attempts a small test order via place_order(). Use only for testing.
    Body JSON: {"symbol":"BTC/USD","type":"Spot","side":"LONG","amount":1.0}
    """
    payload = request.get_json(force=True, silent=True) or {}
    test_symbol = payload.get("symbol", "BTC/USD")
    test_type = payload.get("type", "Spot")
    test_side = payload.get("side", "LONG")
    test_amount = float(payload.get("amount", 1.0))
    side = "buy" if test_side.upper() == "LONG" else "sell"
    res = place_order(test_symbol, test_type, side, test_amount)
    return jsonify({"test_order_result": res})

# -----------------------------------------------------------------------------
# Run (local dev only). On Render/Railway use recommended entrypoint (Procfile)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)
