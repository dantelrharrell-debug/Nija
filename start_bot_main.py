from loguru import logger
from app.nija_client import CoinbaseClient
from app.app.webhook import start_webhook_server   # <-- fixed path

def main():
    logger.info("Starting Nija Bot...")
    
    # Start webhook server (non-blocking)
    start_webhook_server()

    # Initialize Coinbase client
    client = CoinbaseClient()
    logger.info("Coinbase client initialized. Ready to trade.")

    # Add your trading logic here
    # Example:
    # client.place_order(...)
