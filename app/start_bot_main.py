# app/start_bot_main.py
from loguru import logger
from app.nija_client import CoinbaseClient
from app.app.webhook import start_webhook_server  # <--- use app.app

def main():
    logger.info("Starting Nija Bot...")

    client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")

    try:
        start_webhook_server(client)  # pass client if your webhook expects it
        logger.info("Webhook server started successfully.")
    except TypeError:
        start_webhook_server()
        logger.info("Webhook server started successfully (no args).")

    logger.info("Nija Bot is running...")
