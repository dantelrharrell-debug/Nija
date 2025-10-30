# live_monitor.py
import time
import logging
from decimal import Decimal
from nija_client import client  # your live RESTClient

logger = logging.getLogger("nija_monitor")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

def get_usd_balance():
    try:
        balances = client.get_account_balances()
        return Decimal(str(balances.get("USD", 0)))
    except Exception as e:
        logger.warning(f"[MONITOR] Failed to fetch USD balance: {e}")
        return None

def get_btc_balance():
    try:
        balances = client.get_account_balances()
        return Decimal(str(balances.get("BTC", 0)))
    except Exception as e:
        logger.warning(f"[MONITOR] Failed to fetch BTC balance: {e}")
        return None

def get_price():
    try:
        # Adjust product ID if needed
        price = client.get_price("BTC-USD")
        return Decimal(str(price))
    except Exception as e:
        logger.warning(f"[MONITOR] Failed to fetch BTC price: {e}")
        return None

def monitor_loop(sleep_seconds=10):
    logger.info("[MONITOR] Starting live monitoring...")
    while True:
        usd = get_usd_balance()
        btc = get_btc_balance()
        price = get_price()
        if usd is not None and btc is not None and price is not None:
            total_value = usd + btc * price
            logger.info(f"[MONITOR] USD: ${usd} | BTC: {btc} | BTC Price: ${price} | Total Value: ${total_value}")
        time.sleep(sleep_seconds)

if __name__ == "__main__":
    monitor_loop()
