# app/check_funded_account.py

from loguru import logger
from app.nija_client import CoinbaseClient

# Minimum account balance to be considered funded
FUND_THRESHOLD = 1.0  # Adjust as needed

def main():
    logger.info("Checking funded accounts...")

    # Initialize Coinbase client safely
    try:
        client = CoinbaseClient()
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize Coinbase client: {}", e)
        return

    # Fetch accounts
    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error("Failed to fetch accounts: {}", e)
        return

    # Filter funded accounts
    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount >= FUND_THRESHOLD:
            funded_accounts.append((name, amount, currency))

    # Report results
    if funded_accounts:
        logger.info("✅ Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            logger.info(f"   - {name}: {amount} {currency}")
    else:
        logger.warning("⚠️ No funded accounts detected.")

if __name__ == "__main__":
    main()
