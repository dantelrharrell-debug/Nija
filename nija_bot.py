# nija_bot.py
import os
import time
import json
from loguru import logger
from nija_client import get_coinbase_client

# -------------------------
# Environment variables
# -------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")  # unused for standard RESTClient
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")            # unused for standard RESTClient

TRADINGVIEW_SIGNAL_URL = os.environ.get("TRADINGVIEW_SIGNAL_URL")  # URL returning JSON signal
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 5))  # seconds

MIN_POSITION = float(os.environ.get("MIN_POSITION", 0.02))  # 2%
MAX_POSITION = float(os.environ.get("MAX_POSITION", 0.10))  # 10%

# -------------------------
# Instantiate Coinbase client
# -------------------------
client = get_coinbase_client(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
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
        logger.warning(f"Failed to fetch accounts: {e}")
        return []

# -------------------------
# Dynamic sizing
# -------------------------
def calculate_order_size(account, percentage):
    balance = float(account.get("balance", 0))
    size = balance * percentage
    return max(size, 0.001)  # minimum order size 0.001

# -------------------------
# Execute trade safely
# -------------------------
def execute_trade(account, signal):
    # Prevent duplicate trades
    signal_id = signal.get("id") or json.dumps(signal)
    if signal_id in processed_signals:
        logger.debug(f"Signal {signal_id} already processed")
        return
    processed_signals.add(signal_id)

    side = signal.get("side")  # "buy" or "sell"
    product_id = signal.get("product_id", "BTC-USD")
    price = signal.get("price", None)

    # Dynamic position sizing
    percentage = float(signal.get("size_pct", 0.05))
    percentage = max(min(percentage, MAX_POSITION), MIN_POSITION)
    size = calculate_order_size(account, percentage)

    logger.info(f"Placing {side} order for {size} {product_id} at {price} on account {account['id']}")
    try:
        order = client.place_order(
            product_id=product_id,
            side=side,
            size=str(size),
            price=price
        )
        logger.info(f"Order executed: {order}")
    except Exception as e:
        logger.warning(f"Order failed or dry-run: {e}")

# -------------------------
# Main 24/7 loop
# -------------------------
def main_loop():
    logger.info("Starting Nija autonomous 24/7 bot...")
    while True:
        try:
            # 1️⃣ Fetch TradingView signal
            signal = safe_request("GET", TRADINGVIEW_SIGNAL_URL)
            if not signal:
                logger.debug("No signal received")
                time.sleep(POLL_INTERVAL)
                continue

            # 2️⃣ Fetch funded accounts
            funded_accounts = fetch_funded_accounts()
            if not funded_accounts:
                logger.warning("No funded accounts found, skipping trades")
                time.sleep(POLL_INTERVAL)
                continue

            # 3️⃣ Execute trades for all funded accounts
            for acct in funded_accounts:
                execute_trade(acct, signal)

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        time.sleep(POLL_INTERVAL)

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    main_loop()
