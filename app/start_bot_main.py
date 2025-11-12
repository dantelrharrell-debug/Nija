from loguru import logger
from app.nija_client import CoinbaseClient

# Import webhook correctly from nested app
try:
    from app.app.webhook import start_webhook_server
except ImportError as e:
    logger.error("Critical error: Could not import webhook module: {}", e)
    raise SystemExit("Bot cannot start without webhook")

FUND_THRESHOLD = 1.0  # Minimum balance required to be considered "funded"

def main():
    logger.info("Starting Nija Bot...")

    # Initialize Coinbase client
    client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")

    # --- Check for funded accounts ---
    try:
        accounts = client.get_accounts()  # Fetch all accounts
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return

    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount >= FUND_THRESHOLD:
            funded_accounts.append((name, amount, currency))

    if funded_accounts:
        logger.info("Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            logger.info(f" - {name}: {amount} {currency}")
    else:
        logger.warning("No funded accounts detected. Bot will not trade!")
        return  # Stop here to avoid trading without funds

    # Start webhook server with the initialized client
    try:
        start_webhook_server(client)
        logger.info("Webhook server started successfully.")
    except TypeError as te:
        logger.error(f"Failed to start webhook server: {te}")
        return

    # Main bot logic can go here
    logger.info("Nija Bot is running...")

if __name__ == "__main__":
    main()
