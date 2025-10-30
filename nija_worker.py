# nija_worker.py
import logging
import time
from decimal import Decimal, ROUND_DOWN
from nija_client import client, USE_DUMMY

logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Config ---
DRY_RUN = False  # fully live now
MIN_PCT = 0.02
MAX_PCT = 0.10
MIN_USD = 1.0
SLEEP_SECONDS = 10

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# --- Trading logic import ---
try:
    from trading_logic import decide_trade
    logger.info("[NIJA] trading_logic.decide_trade loaded")
except Exception:
    decide_trade = None
    logger.warning("[NIJA] No trading_logic.decide_trade — worker will skip trades")

# --- Helpers ---
def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

def get_usd_balance(client):
    try:
        balances = client.get_account_balances()
        return Decimal(str(balances.get("USD", 0)))
    except Exception as e:
        logger.warning(f"[NIJA] get_usd_balance error: {e}")
        return Decimal("0")

def get_price_for_product(client, product_id):
    try:
        price = client.get_price(product_id)
        return Decimal(str(price))
    except Exception as e:
        logger.warning(f"[NIJA] get_price_for_product error: {e}")
        return None

def place_market_order(client, action, product_id, usd_amount):
    try:
        result = client.place_order(action, product_id, usd_amount)
        logger.info(f"[NIJA] Order result: {result}")
        return result
    except Exception as e:
        logger.error(f"[NIJA] Failed to place order: {e}")
        return None

# --- Main worker ---
def start_worker():
    logger.info("[NIJA] Starting live trading worker")
    while True:
        try:
            if decide_trade:
                signal = decide_trade(client)
            else:
                signal = None

            if signal:
                action = signal.get("action")
                product_id = signal.get("product_id")
                confidence = float(signal.get("confidence", 1.0))

                usd_balance = get_usd_balance(client)
                pct = clamp(confidence * MAX_PCT, MIN_PCT, MAX_PCT)
                usd_to_use = (usd_balance * Decimal(str(pct))).quantize(Decimal("0.01"), ROUND_DOWN)

                if usd_to_use >= MIN_USD:
                    price = get_price_for_product(client, product_id)
                    logger.info(f"[NIJA] {action.upper()} {product_id} for ${usd_to_use} at price {price}")
                    if not DRY_RUN and not USE_DUMMY:
                        place_market_order(client, action, product_id, usd_to_use)
                    else:
                        logger.info("[NIJA] DRY_RUN or DummyClient — skipping order execution")
                else:
                    logger.info(f"[NIJA] Computed order ${usd_to_use} below MIN_USD ${MIN_USD} — skipping")
            else:
                logger.debug("[NIJA] No trading signal this loop")

            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted — exiting")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)

# --- Start worker immediately ---
if __name__ == "__main__":
    start_worker()
