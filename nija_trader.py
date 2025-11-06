# nija_trader.py
import os
import time
from loguru import logger
from nija_coinbase_client import CoinbaseClient
from trading_logic import signal_generator  # your custom logic module

# Initialize Coinbase client
client = CoinbaseClient()

# Settings
TRADE_INTERVAL = 10  # seconds between trade checks
MIN_BALANCE = 10.0   # minimum account balance to trade
PRODUCT_ID = "BTC-USD"  # example, can loop multiple products

def main():
    logger.info("Nija Trader starting...")
    
    # Fetch funded accounts
    funded = client.get_funded_accounts(min_balance=MIN_BALANCE)
    if not funded["ok"]:
        logger.error(f"Failed to fetch funded accounts: {funded.get('error')}")
        return
    
    accounts = funded["funded_accounts"]
    if not accounts:
        logger.warning("No funded accounts above minimum balance.")
        return
    
    logger.info(f"Using funded accounts: {accounts}")
    
    # Main trading loop
    while True:
        for acct in accounts:
            account_id = acct["id"]
            balance = acct["balance"]
            currency = acct["currency"]
            
            # Generate trading signal
            signal = signal_generator(PRODUCT_ID)
            if signal == "buy":
                logger.info(f"Placing BUY order for {PRODUCT_ID} from account {account_id}")
                result = client.place_order(account_id, "buy", PRODUCT_ID, size=balance/2)
            elif signal == "sell":
                logger.info(f"Placing SELL order for {PRODUCT_ID} from account {account_id}")
                result = client.place_order(account_id, "sell", PRODUCT_ID, size=balance/2)
            else:
                logger.info("No signal detected. Skipping trade.")
                result = None

            if result:
                if result["ok"]:
                    logger.info(f"Order placed successfully: {result['order']}")
                else:
                    logger.error(f"Failed to place order: {result['error']}")
        
        logger.info(f"Sleeping {TRADE_INTERVAL} seconds before next trade cycle...")
        time.sleep(TRADE_INTERVAL)

if __name__ == "__main__":
    main()
