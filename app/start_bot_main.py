# app/start_bot_main.py
from loguru import logger
from app.nija_client import CoinbaseClient
from app.webhook import start_webhook_server

def main():
    logger.info("Starting Nija Bot...")

    # Initialize Coinbase client
    main_client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")

    # ----- NEW: Safe funded account check -----
    try:
        accounts = main_client.get_accounts()  # Fetch all accounts
        for acc in accounts:
            logger.info(
                f"[ACCOUNT CHECK] Currency: {acc['currency']} | "
                f"Balance: {acc['balance']['amount']} | "
                f"Available: {acc['available']['amount']}"
            )
        logger.info("Funded account check complete.")
    except Exception as e:
        logger.error(f"Error checking accounts: {e}")
    # -----------------------------------------

    # Start webhook server
    try:
        start_webhook_server(main_client)
        logger.info("Webhook server started successfully.")
    except TypeError:
        # If the server does not accept arguments, call without passing the client
        start_webhook_server()
        logger.info("Webhook server started successfully (no args).")

    logger.info("Nija Bot is running...")
