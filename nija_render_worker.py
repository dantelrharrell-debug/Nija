import time
import logging
from decimal import Decimal
from nija_client import get_client, get_usd_balance, execute_trade, get_position

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# --- Configurable trading parameters ---
MIN_ALLOCATION = 0.02  # 2% of USD balance
MAX_ALLOCATION = 0.10  # 10% of USD balance
TAKE_PROFIT_PERCENT = 0.03   # 3% gain
TRAILING_STOP_PERCENT = 0.02 # 2% trailing loss

def run_worker():
    logger.info("[NIJA-WORKER] Worker started")
    client = get_client()
    if client is None:
        logger.error("[NIJA-WORKER] Coinbase client unavailable. Exiting.")
        return

    positions = {}  # Track active trades

    while True:
        try:
            # --- 1️⃣ Get current USD balance ---
            usd_balance = get_usd_balance(client)

            # --- 2️⃣ Decide allocation (2%-10% of account) ---
            allocation = min(max(usd_balance * 0.05, usd_balance * MIN_ALLOCATION),
                             usd_balance * MAX_ALLOCATION)

            # --- 3️⃣ Execute trade if no active position ---
            if "BTC-USD" not in positions:
                order = execute_trade(client, allocation)
                if order:
                    positions["BTC-USD"] = {
                        "buy_price": float(order['filled_avg_price']),
                        "amount": float(order['filled_size'])
                    }
                    logger.info(f"[NIJA-WORKER] Bought BTC: {positions['BTC-USD']}")

            # --- 4️⃣ Check positions for take profit or trailing stop ---
            for product, pos in list(positions.items()):
                current_price = float(client.get_spot_price(product))
                entry_price = pos["buy_price"]
                amount = pos["amount"]

                # Take profit
                if current_price >= entry_price * (1 + TAKE_PROFIT_PERCENT):
                    client.place_order(product_id=product, side="sell",
                                       type="market", size=amount)
                    logger.info(f"[NIJA-WORKER] TAKE PROFIT: Sold {amount} {product} at {current_price}")
                    del positions[product]
                    continue

                # Trailing stop
                # Update stop price if price moves up
                if "stop_price" not in pos:
                    pos["stop_price"] = entry_price * (1 - TRAILING_STOP_PERCENT)
                else:
                    new_stop = current_price * (1 - TRAILING_STOP_PERCENT)
                    if new_stop > pos["stop_price"]:
                        pos["stop_price"] = new_stop

                # Trigger trailing stop
                if current_price <= pos["stop_price"]:
                    client.place_order(product_id=product, side="sell",
                                       type="market", size=amount)
                    logger.info(f"[NIJA-WORKER] TRAILING STOP: Sold {amount} {product} at {current_price}")
                    del positions[product]

            # --- 5️⃣ Wait before next cycle ---
            time.sleep(10)  # aggressive, adjust as needed

        except Exception as e:
            logger.error(f"[NIJA-WORKER] Error in worker loop: {e}")
            time.sleep(5)
