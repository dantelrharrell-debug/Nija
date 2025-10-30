import os
import logging
import time
from decimal import Decimal, ROUND_DOWN
from trading_logic import decide_trade  # your live strategy

logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Config ---
DRY_RUN = False  # Force fully live
MIN_PCT = float(os.getenv("TRADE_MIN_PCT", "0.02"))
MAX_PCT = float(os.getenv("TRADE_MAX_PCT", "0.10"))
MIN_USD = float(os.getenv("TRADE_MIN_USD", "1"))
SLEEP_SECONDS = int(os.getenv("WORKER_LOOP_SLEEP", "10"))

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# --- Helpers ---
def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

def get_usd_balance(client):
    try:
        if hasattr(client, "get_account_balances"):
            b = client.get_account_balances()
            val = b.get("USD") or b.get("USD", 0)
            return Decimal(str(val))
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
    try:
        if hasattr(client, "get_ticker"):
            res = client.get_ticker(product_id)
            return Decimal(str(res.get("price") or res.get("last") or 0))
    except Exception:
        return None

def place_market_order(client, action, product_id, usd_amount):
    logger.info(f"[NIJA] Placing MARKET {action.upper()} for {product_id} US${usd_amount}")
    if hasattr(client, "market_order"):
        return client.market_order(side=action, product_id=product_id, funds=str(usd_amount))
    if hasattr(client, "place_order"):
        return client.place_order(side=action, product_id=product_id, funds=str(usd_amount))
    raise RuntimeError("No supported order method found")

# --- Main worker ---
def start_worker(client):
    logger.info("[NIJA] start_worker invoked. Fully LIVE mode")
    while True:
        try:
            signal = decide_trade(client)
            if signal:
                action = signal.get("action").lower()
                product_id = signal.get("product_id") or signal.get("symbol")
                confidence = float(signal.get("confidence", 1.0))

                usd_balance = get_usd_balance(client)
                if usd_balance is None:
                    logger.warning("[NIJA] Could not read USD balance; skipping")
                    time.sleep(SLEEP_SECONDS)
                    continue

                pct = clamp(confidence * MAX_PCT, MIN_PCT, MAX_PCT)
                usd_to_use = (usd_balance * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if usd_to_use < Decimal(str(MIN_USD)):
                    logger.warning(f"[NIJA] Computed order ${usd_to_use} below MIN_USD ${MIN_USD}; skipping")
                else:
                    price = get_price_for_product(client, product_id)
                    logger.info(f"[NIJA] Market price for {product_id}: {price}")
                    result = place_market_order(client, action, product_id, usd_to_use)
                    logger.info(f"[NIJA] Order executed: {result}")

            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted; exiting cleanly")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)
