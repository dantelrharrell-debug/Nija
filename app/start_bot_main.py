# app/start_bot_main.py
from loguru import logger
from app.nija_client import CoinbaseClient

# Import webhook safely from nested app folder
try:
    from app.app.webhook import start_webhook_server
except ImportError as e:
    logger.error("Critical error: Could not import webhook module: {}", e)
    raise SystemExit("Bot cannot start without webhook module")

FUND_THRESHOLD = 1.0  # Minimum account balance to trade

def main():
    logger.info("Starting Nija Bot...")

    # Initialize client
    client = CoinbaseClient()

    # Fetch accounts
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error("Failed to fetch accounts: {}", e)
        raise SystemExit("Cannot continue without account info")

    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount >= FUND_THRESHOLD:
            funded_accounts.append((name, amount, currency))

    if not funded_accounts:
        logger.warning("No funded accounts detected. Bot will not trade!")
        return
    else:
        logger.info("Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            logger.info(f" - {name}: {amount} {currency}")

    # Start webhook server
    start_webhook_server(client)
    logger.info("Webhook server started successfully.")
    logger.info("Nija Bot is running... Ready to trade!")

if __name__ == "__main__":
    main()
