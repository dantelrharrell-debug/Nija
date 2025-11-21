import time
from loguru import logger
from nija_client import CoinbaseClient
from config import LIVE_TRADING, TRADING_ACCOUNT_ID

# Initialize client
client = CoinbaseClient()

def coinbase_loop():
    logger.info("🚀 Coinbase trading loop started")
    while True:
        try:
            accounts = client.list_accounts()
            # Example: just log balances for now
            for acct in accounts:
                balance = float(acct.get("balance", {}).get("amount", 0))
                currency = acct.get("balance", {}).get("currency", "")
                logger.info(f"Account {acct['id']} balance: {balance} {currency}")

                # Here you could add your trading logic:
                # if LIVE_TRADING:
                #     client.place_order(...)  

        except Exception as e:
            logger.exception(f"Error in Coinbase loop: {e}")

        # Sleep for a configurable interval
        time.sleep(30)  # check every 30s
