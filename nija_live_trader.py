# nija_live_trader.py
import os
import time
from loguru import logger
from nija_coinbase_client import CoinbaseClient
from trading_logic import signal_generator

# -------------------------
# CONFIGURATION
# -------------------------
TRADE_INTERVAL = int(os.getenv("TRADE_INTERVAL", 10))   # seconds
MIN_BALANCE = float(os.getenv("MIN_BALANCE", 10.0))    # minimum USD per account
POSITION_SIZE = float(os.getenv("POSITION_SIZE", 0.5)) # fraction of balance to trade
PRODUCTS = os.getenv("PRODUCTS", "BTC-USD,ETH-USD,LTC-USD").split(",")

logger.info("Nija Live Trader starting...")

# -------------------------
# INITIALIZE CLIENT
# -------------------------
client = CoinbaseClient()

# -------------------------
# PREFLIGHT CHECK
# -------------------------
def preflight_check():
    """
    Verify API connectivity and funded accounts
    """
    funded = client.get_funded_accounts(min_balance=MIN_BALANCE)
    if not funded.get("ok"):
        logger.error(f"Failed preflight check: {funded.get('error')}")
        return []

    accounts = funded.get("funded_accounts", [])
    logger.info(f"Funded accounts ready: {[a['currency'] for a in accounts]}")
    return accounts

# -------------------------
# MAIN TRADING LOOP
# -------------------------
def main():
    accounts = preflight_check()
    if not accounts:
        logger.warning("No funded accounts found. Exiting...")
        return

    while True:
        try:
            for acct in accounts:
                account_id = acct["id"]
                balance = float(acct["balance"])
                currency = acct["currency"]

                if balance < MIN_BALANCE:
                    logger.warning(f"Skipping {currency} due to low balance: {balance}")
                    continue

                for product in PRODUCTS:
                    signal = signal_generator(product)
                    size = balance * POSITION_SIZE

                    if signal == "buy":
                        res = client.place_order(account_id, "buy", product, size=size)
                    elif signal == "sell":
                        res = client.place_order(account_id, "sell", product, size=size)
                    else:
                        continue

                    if res.get("ok"):
                        logger.info(f"Order executed: {res['order']}")
                    else:
                        logger.error(f"Order failed: {res.get('error')}")

            logger.info(f"Sleeping {TRADE_INTERVAL}s for next cycle...")
            time.sleep(TRADE_INTERVAL)

        except Exception as e:
            logger.exception(f"Unexpected error in trading loop: {e}")
            time.sleep(TRADE_INTERVAL)

# -------------------------
# ENTRY POINT
# -------------------------
if __name__ == "__main__":
    main()
