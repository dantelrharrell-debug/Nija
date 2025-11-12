# nija_app.py
from nija_client import CoinbaseClient
from loguru import logger

# Position sizing rules
MIN_POSITION = 0.02  # 2% of account equity
MAX_POSITION = 0.10  # 10% of account equity

def main():
    # Initialize Coinbase client
    try:
        client = CoinbaseClient()
    except ValueError:
        exit("Cannot start bot without valid Coinbase credentials")

    # Test connection
    try:
        accounts = client.get_accounts()
        if not accounts.get("data"):
            logger.error("❌ Connection test failed! /accounts returned no data.")
            return
        logger.info("✅ Connected to Coinbase! Accounts retrieved.")
    except Exception as e:
        logger.error(f"❌ Connection test failed: {e}")
        return

    # Main trading loop (placeholder for TradingView integration)
    logger.info("Starting live trading loop...")
    while True:
        # Example: listen for alerts (replace with actual TradingView integration)
        # alert = get_tradingview_alert()
        # if alert:
        #     size = calculate_position(alert["equity"], MIN_POSITION, MAX_POSITION)
        #     execute_trade(client, alert, size)
        break  # remove in production

# Optional helper for position sizing
def calculate_position(account_equity, min_pct, max_pct):
    position = account_equity * min_pct
    if position > account_equity * max_pct:
        position = account_equity * max_pct
    return position

# Placeholder for executing a trade
def execute_trade(client, alert, size):
    logger.info(f"Executing trade: {alert}, size: {size}")
    # Implement buy/sell logic here

if __name__ == "__main__":
    main()
