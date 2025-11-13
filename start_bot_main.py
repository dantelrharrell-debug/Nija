# app/start_bot_main.py
import time
from loguru import logger

# Correct import depending on your installed version
from coinbase_advanced_py.rest import CoinbaseRESTClient

logger.info("start_bot_main.py loaded")

def start_bot_main():
    logger.info("Bot logic starting...")
    try:
        client = CoinbaseRESTClient(
            api_key="YOUR_API_KEY",
            api_secret="YOUR_API_SECRET",
            api_passphrase="YOUR_PASSPHRASE",
            base_url="https://api.pro.coinbase.com"
        )
        logger.info("Coinbase client initialized")
        accounts = client.get_accounts()
        logger.info("Accounts: {}", accounts)

        while True:
            logger.info("Bot heartbeat")
            time.sleep(60)

    except Exception as e:
        logger.exception("Error in start_bot_main: {}", e)
        raise
