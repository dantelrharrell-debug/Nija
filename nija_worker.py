import time
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_worker")

# --- Position sizing settings ---
MIN_PCT = 0.02  # 2% minimum
MAX_PCT = 0.1   # 10% maximum
MIN_USD = 1.0   # minimum USD per trade

def calculate_order_size(equity: Decimal, pct: float):
    """
    Returns the order size in USD, clamped to MIN_USD.
    """
    size = equity * Decimal(pct)
    if size < MIN_USD:
        size = Decimal(MIN_USD)
    return size

# --- Example trading logic ---
def decide_trade():
    """
    Replace this with your custom logic.
    Returns 'buy', 'sell', or None
    """
    # Example placeholder: always buy 5% of account
    return "buy", 0.05  # trade type, position % of equity

# --- Place order function ---
def place_order(trade_type: str, position_pct: float):
    equity = get_usd_balance(client)
    order_size = calculate_order_size(equity, position_pct)
    logger.info(f"[NIJA] Preparing {trade_type.upper()} order for ${order_size:.2f} ({position_pct*100:.1f}% of equity)")

    try:
        # Example: market order for BTC-USD
        order = client.place_order(
            product_id="BTC-USD",
            side=trade_type,
            order_type="market",
            funds=str(order_size)
        )
        logger.info(f"[NIJA] Order executed: {order}")
    except Exception as e:
        logger.error(f"[NIJA] Order failed: {e}")

# --- Worker loop ---
def run_worker():
    logger.info("[NIJA] Starting live trading worker...")
    while True:
        try:
            trade_signal = decide_trade()
            if trade_signal:
                trade_type, pct = trade_signal
                place_order(trade_type, pct)
            else:
                logger.info("[NIJA] No trade signal. Waiting...")
            time.sleep(10)  # adjust interval as needed
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"[NIJA] Unexpected error in worker loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
