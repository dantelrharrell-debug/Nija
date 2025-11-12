from loguru import logger
from app.nija_client import CoinbaseClient

# Correct import: no circular references
from app.app.webhook import start_webhook_server  # webhook.py must NOT import start_bot_main

FUND_THRESHOLD = 1.0  # Minimum balance required

def main():
    logger.info("Starting Nija Bot...")

    client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")

    # Check for funded accounts
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return

    funded_accounts = [
        (acct.get("name", "Unnamed"),
         float(acct.get("balance", {}).get("amount", 0)),
         acct.get("balance", {}).get("currency", "USD"))
        for acct in accounts
        if float(acct.get("balance", {}).get("amount", 0)) >= FUND_THRESHOLD
    ]

    if not funded_accounts:
        logger.warning("No funded accounts detected. Bot will not trade!")
        return

    logger.info("Funded accounts detected:")
    for name, amount, currency in funded_accounts:
        logger.info(f" - {name}: {amount} {currency}")

    # Start webhook server with the client
    try:
        start_webhook_server(client)
        logger.info("Webhook server started successfully.")
    except Exception as e:
        logger.error(f"Failed to start webhook server: {e}")
        return

    logger.info("Nija Bot is running...")

if __name__ == "__main__":
    main()
