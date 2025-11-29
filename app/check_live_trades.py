import os
import logging
from nija_client import Client  # Your Coinbase client wrapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

def check_live_trading():
    live_flag = os.environ.get("LIVE_TRADING")
    if live_flag != "1":
        logging.warning("LIVE_TRADING environment variable is not enabled!")
        return False

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB")
        )
    except Exception as e:
        logging.error(f"Could not initialize Coinbase client: {e}")
        return False

    # Quick test: get account balances or recent trades
    try:
        balances = client.get_balances()
        logging.info(f"Account balances: {balances}")
    except Exception as e:
        logging.error(f"Could not fetch balances: {e}")
        return False

    try:
        recent_trades = client.get_recent_trades(limit=1)  # adapt to your client method
        if recent_trades:
            logging.info(f"Recent trades detected: {recent_trades}")
            logging.info("✅ Bot is LIVE trading!")
            return True
        else:
            logging.info("No recent trades. Bot may be idle or in dry run mode.")
            return False
    except Exception as e:
        logging.error(f"Could not fetch recent trades: {e}")
        return False

if __name__ == "__main__":
    check_live_trading()
