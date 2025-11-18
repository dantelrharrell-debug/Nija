# nija_bot.py
import os
import time
import json
from loguru import logger
from nija_client import get_coinbase_client

# -------------------------
# Environment variables
# -------------------------
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
TRADINGVIEW_SIGNAL_URL = os.environ.get("TRADINGVIEW_SIGNAL_URL")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 5))
MIN_POSITION = float(os.environ.get("MIN_POSITION", 0.02))
MAX_POSITION = float(os.environ.get("MAX_POSITION", 0.10))

# -------------------------
# Instantiate client
# -------------------------
client = get_coinbase_client(
    pem=COINBASE_PEM_CONTENT,
    org_id=COINBASE_ORG_ID
)

# -------------------------
# Memory for processed signals
# -------------------------
processed_signals = set()

# -------------------------
# Safe HTTP request
# -------------------------
def safe_request(method, url, **kwargs):
    try:
        import requests
        r = requests.request(method, url, timeout=10, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Request failed: {e}")
        return None

# -------------------------
# Fetch funded accounts
# -------------------------
def fetch_funded_accounts():
    try:
        accounts = client.get_accounts()
        funded = [a for a in accounts if float(a.get("balance", 0)) > 0]
        return funded
    except Exception as e:
        logger.warning(f"Failed to fetch accounts (dry-run or error): {e}")
        return []

# -------------------------
# Dynamic sizing
# -------------------------
def calculate_order_size(account, percentage):
    balance = float(account.get("balance", 0))
    size = balance * percentage
    return max(size, 0.001)  # minimum order size

# -------------------------
# Execute trade safely
# -------------------------
def execute_trade(account, signal):
    signal_id = signal.get("id") or json.dumps(signal)
    if signal_id in processed_signals:
        return
    processed_signals.add(signal_id)

    side = signal.get("side")  # "buy" or "sell"
    product_id = signal.get("product_id", "BTC-USD")
    price = signal.get("price", None)
    percentage = float(signal.get("size_pct", 0.05))
    percentage = max(min(percentage, MAX_POSITION), MIN_POSITION)
    size = calculate_order_size(account, percentage)

    logger.info(f"Placing {side} order: {size} {product_id} at {price}")
    try:
        order = client.place_order(
            product_id=product_id,
            side=side,
            size=str(size),
            price=price
        )
        logger.info(f"Order result: {order}")
    except Exception as e:
        logger.warning(f"Order not executed (dry-run or error): {e}")

# -------------------------
# Main 24/7 loop
# -------------------------
def main_loop():
    logger.info("Starting Nija Advanced 24/7 bot...")
    while True:
        try:
            signal = safe_request("GET", TRADINGVIEW_SIGNAL_URL)
            if not signal:
                time.sleep(POLL_INTERVAL)
                continue

            funded_accounts = fetch_funded_accounts()
            if not funded_accounts:
                logger.warning("No funded accounts, skipping trades")
                time.sleep(POLL_INTERVAL)
                continue

            for acct in funded_accounts:
                execute_trade(acct, signal)

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main_loop()
