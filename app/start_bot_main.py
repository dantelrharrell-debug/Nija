# app/start_bot_main.py

from loguru import logger
from app.nija_client import CoinbaseClient
from app.app.webhook import start_webhook_server  # nested webhook import

FUND_THRESHOLD = 1.0  # minimum balance to be considered funded

def check_funded_accounts(client):
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error("Failed to fetch accounts: {}", e)
        return []

    funded = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount >= FUND_THRESHOLD:
            funded.append((name, amount, currency))
    return funded

def main():
    logger.info("Starting Nija Bot...")

    # Initialize Coinbase client
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Cannot initialize Coinbase client: {}", e)
        return

    # Check funded accounts
    funded_accounts = check_funded_accounts(client)
    if not funded_accounts:
        logger.warning("No funded accounts detected. Bot will not trade!")
        return
    else:
        logger.info("✅ Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            logger.info(f" - {name}: {amount} {currency}")

    # Start webhook
    try:
        start_webhook_server(client)
        logger.info("Webhook server started successfully.")
    except Exception as e:
        logger.error("Webhook failed to start: {}", e)
        return

    logger.info("Nija Bot is running... ready to trade!")

if __name__ == "__main__":
    main()
