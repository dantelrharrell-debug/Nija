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
POSITION_SIZE = 0.5  # fraction of balance per trade
PRODUCTS = ["BTC-USD", "ETH-USD", "LTC-USD"]  # list of trading pairs

def main():
    logger.info("Nija Multi-Coin Trader starting...")

    # Fetch funded accounts
    funded = client.get_funded_accounts(min_balance=MIN_BALANCE)
    if not funded["ok"]:
        logger.error(f"Failed to fetch funded accounts: {funded.get('error')}")
        return
    
    accounts = funded["funded_accounts"]
    if not accounts:
        logger.warning("No funded accounts above minimum balance.")
        return
    
    logger.info(f"Using funded accounts: {[acct['currency'] for acct in accounts]}")
    
    # Main trading loop
    while True:
        for acct in accounts:
            account_id = acct["id"]
            balance = acct["balance"]
            currency = acct["currency"]

            for product in PRODUCTS:
                # Generate trading signal
                signal = signal_generator(product)
                size = balance * POSITION_SIZE

                if signal == "buy":
                    logger.info(f"[{currency}] Placing BUY order for {product} (size: {size})")
                    result = client.place_order(account_id, "buy", product, size=size)
                elif signal == "sell":
                    logger.info(f"[{currency}] Placing SELL order for {product} (size: {size})")
                    result = client.place_order(account_id, "sell", product, size=size)
                else:
                    logger.info(f"[{currency}] No signal detected for {product}. Skipping trade.")
                    continue

                if result:
                    if result["ok"]:
                        logger.info(f"Order placed successfully: {result['order']}")
                    else:
                        logger.error(f"Failed to place order: {result['error']}")

        logger.info(f"Sleeping {TRADE_INTERVAL} seconds before next trade cycle...")
        time.sleep(TRADE_INTERVAL)

if __name__ == "__main__":
    main()
