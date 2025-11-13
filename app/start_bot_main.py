import time
from app.start_bot_main import main as start_bot_main
from app.nija_client import CoinbaseClient
from loguru import logger

def run_bot():
    try:
        logger.info("Starting Nija Bot...")
        
        # Initialize Coinbase client
        client = CoinbaseClient()  # reads from .env
        logger.info(f"CoinbaseClient initialized with org ID {client.org_id}")

        # Start bot logic
        start_bot_main(client)
        logger.info("Nija bot started successfully.")

    except Exception as e:
        logger.error(f"Fatal error starting bot: {e}")

if __name__ == "__main__":
    run_bot()
    logger.info("Nija bot is now running and container will stay alive.")

    # Keep container alive indefinitely
    while True:
        time.sleep(60)
