# app/check_funded_account.py

from loguru import logger
from app.nija_client import CoinbaseClient

def main():
    logger.info("Checking funded Coinbase accounts...")

    try:
        client = CoinbaseClient()  # Uses your JWT auth from .env
        logger.info("Coinbase client initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize Coinbase client: {}", e)
        return

    try:
        accounts = client.get_accounts()
    except Exception as e:
        logger.error("Failed to fetch accounts: {}", e)
        return

    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount > 0:
            funded_accounts.append((name, amount, currency))

    if funded_accounts:
        logger.info("✅ Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            print(f"{name}: {amount} {currency}")
    else:
        logger.warning("⚠️ No funded accounts found. Check your API keys, JWT, or org ID.")

if __name__ == "__main__":
    main()
