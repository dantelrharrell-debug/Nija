# start_bot_main.py
from loguru import logger

# Import Coinbase client
from app.nija_client import CoinbaseClient

# Import the webhook server from nested app/app
from app.app.webhook import start_webhook_server


def main():
    logger.info("Starting Nija Bot...")

    # Initialize Coinbase client
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        return

    # Start webhook server (for TradingView alerts)
    try:
        start_webhook_server(client)
        logger.info("Webhook server started successfully.")
    except Exception as e:
        logger.error(f"Failed to start webhook server: {e}")
        return

    logger.info("Nija Bot is running...")
