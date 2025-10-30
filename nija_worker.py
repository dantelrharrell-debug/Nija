import logging

logger = logging.getLogger("nija_worker")

# --- DEBUG PATCH START ---
def log_debug_state(market_data=None, decision=None, trade_result=None, client=None):
    """
    Prints market data, trade decisions, executed trades, and account balances.
    Safe for live trading.
    """
    if market_data:
        price = market_data.get("price")
        logger.info(f"[NIJA-DEBUG] Market price: {price}")

    if decision is not None:
        logger.info(f"[NIJA-DEBUG] Trade decision: {decision}")

    if trade_result is not None:
        logger.info(f"[NIJA-DEBUG] Trade executed: {trade_result}")

    # Log account balances if client is provided
    if client:
        try:
            balances = client.get_account_balances()  # Should return dict like {'USD': xx, 'BTC': xx}
            logger.info(f"[NIJA-DEBUG] Account balances: {balances}")
        except Exception as e:
            logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
# --- DEBUG PATCH END ---

# nija_worker.py
import os
import logging
import time
from decimal import Decimal, ROUND_DOWN

# -----------------------------
# --- Setup main logger ------
# -----------------------------
logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# -----------------------------
# --- Trade file logger -------
# -----------------------------
trade_logger = logging.getLogger("nija_trades")
trade_logger.setLevel(logging.INFO)
if not trade_logger.handlers:
    file_handler = logging.FileHandler("nija_trades.log")
    formatter = logging.Formatter("%(asctime)s - %(message)s")
    file_handler.setFormatter(formatter)
    trade_logger.addHandler(file_handler)

# -----------------------------
# --- Config (env-overridable)
# -----------------------------
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")
MIN_PCT = float(os.getenv("TRADE_MIN_PCT", "0.02"))   # 2% default
MAX_PCT = float(os.getenv("TRADE_MAX_PCT", "0.10"))   # 10% default
MIN_USD = float(os.getenv("TRADE_MIN_USD", "1"))      # min $1 order
SLEEP_SECONDS = int(os.getenv("WORKER_LOOP_SLEEP", "10"))

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# -----------------------------
# --- Strategy hook ----------
# -----------------------------
try:
    from trading_logic import decide_trade
    logger.info("[NIJA] trading_logic.decide_trade loaded")
except Exception:
    decide_trade = None
    logger.warning("[NIJA] No trading_logic.decide_trade — worker will not place orders until you provide it")

# -----------------------------
# --- Helper functions -------
# -----------------------------
def get_usd_balance(client):
    try:
        if hasattr(client, "get_account_balances"):
            b = client.get_account_balances()
            return Decimal(str(b.get("USD", 0)))
        if hasattr(client, "get_accounts"):
            accs = client.get_accounts()
            for a in accs:
                currency = a.get("currency") if isinstance(a, dict) else getattr(a, "currency", None)
                avail = a.get("available_balance") if isinstance(a, dict) else getattr(a, "available_balance", None)
                if str(currency).upper() in ("USD", "USDC"):
                    return Decimal(str(avail or 0))
    except Exception as e:
        logger.warning(f"[NIJA] get_usd_balance error: {e}")
    return None

def get_price_for_product(client, product_id):
    attempts = [
        lambda c, p: getattr(c, "get_ticker", None) and c.get_ticker(p),
        lambda c, p: getattr(c, "get_product_ticker", None) and c.get_product_ticker(p),
        lambda c, p: getattr(c, "get_spot_price", None) and c.get_spot_price(p),
        lambda c, p: getattr(c, "get_price", None) and c.get_price(p),
        lambda c, p: getattr(c, "ticker", None) and c.ticker(p),
    ]
    for fn in attempts:
        try:
            res = fn(client, product_id)
            if res is None:
                continue
            if isinstance(res, (int, float, Decimal, str)):
                return Decimal(str(res))
            if isinstance(res, dict):
                for k in ("price", "last", "price_usd", "amount", "ask"):
                    if k in res and res[k] is not None:
                        return Decimal(str(res[k]))
            val = getattr(res, "price", None) or getattr(res, "last", None)
            if val is not None:
                return Decimal(str(val))
        except Exception:
            continue
    return None

def place_market_order(client, action, product_id, usd_amount):
    logger.info(f"[NIJA] Placing MARKET {action.upper()} for {product_id} US${usd_amount}")
    candidates = [
        ("market_order_buy", lambda c: getattr(c, "market_order_buy", None) and c.market_order_buy(**{"product_id":product_id, "usd":str(usd_amount)})),
        ("market_order", lambda c: getattr(c, "market_order", None) and c.market_order(side=action, product_id=product_id, funds=str(usd_amount))),
        ("buy", lambda c: getattr(c, "buy", None) and c.buy(amount=str(usd_amount), product_id=product_id)),
        ("place_order", lambda c: getattr(c, "place_order", None) and c.place_order(side=action, product_id=product_id, funds=str(usd_amount))),
    ]
    last_exc = None
    for name, fn in candidates:
        try:
            method = fn(client)
            if method is None:
                continue
            logger.info(f"[NIJA] Used method {name} to place order")
            return method
        except Exception as e:
            logger.warning(f"[NIJA] Attempt with {name} failed: {e}")
            last_exc = e
    raise RuntimeError(f"No supported order method found (last error: {last_exc})")

def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

# -----------------------------
# --- Main worker ------------
# -----------------------------
def start_worker(client):
    logger.info(f"[NIJA] start_worker invoked. DRY_RUN={DRY_RUN}")
    if decide_trade is None:
        logger.warning("[NIJA] No trading_logic.decide_trade available — cannot place trades")
    while True:
        try:
            signal = decide_trade(client) if decide_trade else None
            if signal:
                action = str(signal.get("action")).lower()
                product_id = signal.get("product_id") or signal.get("symbol")
                confidence = float(signal.get("confidence", 1.0))

                logger.info(f"[NIJA] Received signal action={action} product={product_id} confidence={confidence}")

                if action not in ("buy", "sell") or not product_id:
                    logger.warning("[NIJA] Invalid action or missing product_id; skipping")
                else:
                    usd_balance = get_usd_balance(client)
                    if usd_balance is None:
                        logger.warning("[NIJA] Cannot get USD balance; skipping")
                    else:
                        pct = clamp(confidence * MAX_PCT, MIN_PCT, MAX_PCT)
                        usd_to_use = (usd_balance * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                        if usd_to_use < Decimal(str(MIN_USD)):
                            logger.warning(f"[NIJA] Order ${usd_to_use} below MIN_USD; skipping")
                        else:
                            price = get_price_for_product(client, product_id)
                            logger.info(f"[NIJA] Market price for {product_id}: {price}")
                            if DRY_RUN:
                                logger.info(f"[NIJA] DRY_RUN enabled — would place {action} for ${usd_to_use} on {product_id}")
                            else:
                                try:
                                    result = place_market_order(client, action, product_id, usd_to_use)
                                    logger.info(f"[NIJA] Order result: {result}")
                                    trade_logger.info(f"{action.upper()} {product_id} ${usd_to_use} -> {result}")
                                except Exception as e:
                                    logger.error(f"[NIJA] Failed to place order: {e}")
            else:
                logger.debug("[NIJA] No signal from strategy this loop")

            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted; exiting cleanly")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)
