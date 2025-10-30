# nija_worker.py
import logging, time
from decimal import Decimal, ROUND_DOWN
from nija_client import client

logger = logging.getLogger("nija_worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Config ---
DRY_RUN = False  # FULL LIVE
MIN_PCT = 0.02
MAX_PCT = 0.1
MIN_USD = 1.0
SLEEP_SECONDS = 10

logger.info(f"[NIJA] Worker config DRY_RUN={DRY_RUN} MIN_PCT={MIN_PCT} MAX_PCT={MAX_PCT} MIN_USD={MIN_USD}")

# --- Load your trading logic ---
try:
    from trading_logic import decide_trade
    logger.info("[NIJA] trading_logic.decide_trade loaded")
except Exception:
    decide_trade = None
    logger.warning("[NIJA] trading_logic.decide_trade NOT found — worker will skip trades until added")

# --- Helpers ---
def clamp(n, minn, maxn):
    return max(minn, min(maxn, n))

def get_usd_balance(client):
    try:
        balances = client.get_account_balances()
        return Decimal(str(balances.get("USD", 0)))
    except Exception as e:
        logger.error(f"[NIJA] get_usd_balance error: {e}")
        return Decimal("0")

def get_price(client, product_id):
    try:
        return client.get_price(product_id)
    except Exception as e:
        logger.error(f"[NIJA] get_price error: {e}")
        return None

def place_market_order(client, action, product_id, usd_amount):
    logger.info(f"[NIJA] Placing MARKET {action.upper()} for {product_id} US${usd_amount}")
    return client.place_order(action, product_id, usd_amount)

# --- Main worker ---
def start_worker(client):
    logger.info("[NIJA] Starting live trading worker")
    if decide_trade is None:
        logger.warning("[NIJA] No strategy loaded — add decide_trade for active trading")
    while True:
        try:
            signal = decide_trade(client) if decide_trade else None
            if signal:
                action = signal.get("action").lower()
                product_id = signal.get("product_id") or signal.get("symbol")
                confidence = float(signal.get("confidence", 1.0))

                if action not in ("buy", "sell") or not product_id:
                    logger.warning("[NIJA] Invalid signal — skipping")
                else:
                    usd_balance = get_usd_balance(client)
                    pct = clamp(confidence * MAX_PCT, MIN_PCT, MAX_PCT)
                    usd_to_use = (usd_balance * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                    if usd_to_use >= MIN_USD:
                        price = get_price(client, product_id)
                        logger.info(f"[NIJA] Market price {product_id}: {price}")
                        try:
                            result = place_market_order(client, action, product_id, usd_to_use)
                            logger.info(f"[NIJA] Order executed: {result}")
                        except Exception as e:
                            logger.error(f"[NIJA] Order failed: {e}")
                    else:
                        logger.info(f"[NIJA] Order ${usd_to_use} below MIN_USD, skipping")
            time.sleep(SLEEP_SECONDS)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker interrupted, exiting")
            break
        except Exception as e:
            logger.exception(f"[NIJA] Worker loop error: {e}")
            time.sleep(5)

# --- Auto-start ---
start_worker(client)
