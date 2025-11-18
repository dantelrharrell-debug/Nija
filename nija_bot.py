# nija_bot.py
import os
import time
import requests
from loguru import logger
from nija_client import get_coinbase_client

# -------------------------
# Environment
# -------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

TRADINGVIEW_SIGNAL_URL = os.environ.get("TRADINGVIEW_SIGNAL_URL")  # Webhook or JSON URL
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 5))  # seconds

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
# Safe HTTP request
# -------------------------
def safe_request(method, url, **kwargs):
    try:
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
# Execute trade
# -------------------------
def execute_trade(account, signal):
    try:
        side = signal.get("side")  # "buy" or "sell"
        product_id = signal.get("product_id", "BTC-USD")
        size = signal.get("size", "0.001")
        price = signal.get("price", None)

        logger.info(f"Placing {side} order for {size} {product_id} at {price} on account {account['id']}")
        order = client.place_order(
            product_id=product_id,
            side=side,
            size=size,
            price=price
        )
        logger.info(f"Order response: {order}")
    except Exception as e:
        logger.warning(f"Order failed or dry-run: {e}")

# -------------------------
# Main 24/7 loop
# -------------------------
def main_loop():
    logger.info("Starting Nija 24/7 bot...")
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
                logger.warning("No funded accounts found, skipping trade")
                time.sleep(POLL_INTERVAL)
                continue

            # 3️⃣ Execute trades for all funded accounts
            for acct in funded_accounts:
                execute_trade(acct, signal)

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        # 4️⃣ Wait before next poll
        time.sleep(POLL_INTERVAL)

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    main_loop()
