from loguru import logger
from app.nija_client import CoinbaseClient
from app.app.webhook import start_webhook_server  # Nested app import

FUND_THRESHOLD = 1.0

def main():
    logger.info("Starting Nija Bot...")

    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
        return

    # --- Check funded accounts ---
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return

    funded_accounts = [
        (acct.get("name", "Unnamed"),
         float(acct.get("balance", {}).get("amount", 0)),
         acct.get("balance", {}).get("currency", "USD"))
        for acct in accounts if float(acct.get("balance", {}).get("amount", 0)) >= FUND_THRESHOLD
    ]

    if not funded_accounts:
        logger.warning("No funded accounts detected. Bot will not trade!")
        return

    logger.info("Funded accounts detected:")
    for name, amount, currency in funded_accounts:
        logger.info(f" - {name}: {amount} {currency}")

    # Start webhook server
    try:
        start_webhook_server(client)
        logger.info("Webhook server started successfully.")
    except Exception as e:
        logger.error(f"Failed to start webhook server: {e}")
        return

    logger.info("Nija Bot is running...")

if __name__ == "__main__":
    main()
