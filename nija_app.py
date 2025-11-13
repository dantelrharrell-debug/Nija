import time
from loguru import logger
from app.start_bot_main import main as start_bot_main
from app.nija_client import CoinbaseClient

CHECK_INTERVAL = 10  # seconds between each account/signal check

def run_bot():
    try:
        logger.info("Starting Nija Bot...")

        # Initialize Coinbase client
        client = CoinbaseClient()  # reads from .env
        logger.info(f"CoinbaseClient initialized with org ID {client.org_id}")

        # Start bot main routine (setup, initial fetch, etc.)
        start_bot_main(client)
        logger.info("Nija bot started successfully.")

        # Main loop: keep checking accounts/signals
        while True:
            try:
                accounts = client.get_accounts()  # fetch accounts
                logger.info(f"Fetched {len(accounts)} accounts successfully.")

                # Here you can call your trading logic
                # e.g., check signals, execute trades
                # run_trading_logic(accounts)

            except Exception as e:
                logger.error(f"Error during account/signal check: {e}")

            time.sleep(CHECK_INTERVAL)

    except Exception as e:
        logger.error(f"Fatal error starting bot: {e}")
        raise

if __name__ == "__main__":
    run_bot()
    print("Nija bot is now running...")
