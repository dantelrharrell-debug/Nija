import os
import time
import logging
from decimal import Decimal, ROUND_DOWN

logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Config ---
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")
MIN_PCT = float(os.getenv("TRADE_MIN_PCT", "0.02"))
MAX_PCT = float(os.getenv("TRADE_MAX_PCT", "0.10"))
MIN_USD = float(os.getenv("TRADE_MIN_USD", "1"))
SLEEP_SECONDS = int(os.getenv("WORKER_LOOP_SLEEP", "10"))

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# --- Trading strategy hook ---
try:
    from trading_logic import decide_trade
    logger.info("[NIJA] trading_logic.decide_trade loaded")
except Exception:
    decide_trade = None
    logger.warning("[NIJA] trading_logic.decide_trade NOT found — worker will skip trades")

# --- Helpers ---
def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

def get_usd_balance(client):
    try:
        if hasattr(client, "get_account_balances"):
            b = client.get_account_balances()
            return Decimal(str(b.get("USD", 0)))
        if hasattr(client, "get_accounts"):
            for a in client.get_accounts():
                cur = a.get("currency") if isinstance(a, dict) else getattr(a, "currency", None)
                avail = a.get("available_balance") if isinstance(a, dict) else getattr(a, "available_balance", None)
                if str(cur).upper() in ("USD", "USDC"):
                    return Decimal(str(avail or 0))
    except Exception as e:
        logger.warning(f"[NIJA] get_usd_balance error: {e}")
    return None

def get_price_for_product(client, product_id):
    try:
        if hasattr(client, "get_ticker"):
            res = client.get_ticker(product_id)
            return Decimal(str(res.get("price", res.get("last", 0))))
    except Exception:
        return None

def place_market_order(client, action, product_id, usd_amount):
    try:
        if hasattr(client, "market_order"):
            return client.market_order(side=action, product_id=product_id, funds=str(usd_amount))
        if hasattr(client, "buy") and action=="buy":
            return client.buy(amount=str(usd_amount), product_id=product_id)
        if hasattr(client, "sell") and action=="sell":
            return client.sell(amount=str(usd_amount), product_id=product_id)
    except Exception as e:
        logger.error(f"[NIJA] Failed to place order: {e}")
    raise RuntimeError("No supported order method found")

# --- Main worker ---
def start_worker(client):
    logger.info(f"[NIJA] start_worker invoked. DRY_RUN={DRY_RUN}")
    if decide_trade is None:
        logger.warning("[NIJA] No strategy loaded — skipping trades")
    while True:
        try:
            signal = decide_trade(client) if decide_trade else None
            if signal:
                action = str(signal.get("action")).lower()
                product_id = signal.get("product_id") or signal.get("symbol")
                confidence = float(signal.get("confidence", 1.0))
                if action not in ("buy","sell") or not product_id:
                    logger.warning("[NIJA] Invalid trade signal — skipping")
                else:
                    usd_balance = get_usd_balance(client)
                    if usd_balance is None:
                        logger.warning("[NIJA] USD balance unknown — skipping")
                    else:
                        pct = clamp(confidence*MAX_PCT, MIN_PCT, MAX_PCT)
                        usd_to_use = (usd_balance*Decimal(str(pct))).quantize(Decimal("0.01"), ROUND_DOWN)
                        if usd_to_use < Decimal(str(MIN_USD)):
                            logger.warning(f"[NIJA] Order ${usd_to_use} below MIN_USD — skipping")
                        else:
                            price = get_price_for_product(client, product_id)
                            logger.info(f"[NIJA] Market price for {product_id}: {price}")
                            if DRY_RUN:
                                logger.info(f"[NIJA] DRY_RUN — would {action} ${usd_to_use}")
                            else:
                                result = place_market_order(client, action, product_id, usd_to_use)
                                logger.info(f"[NIJA] Order placed: {result}")
            else:
                logger.debug("[NIJA] No signal from strategy")
            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted — exiting cleanly")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)
