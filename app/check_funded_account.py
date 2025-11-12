# check_funded_account.py
from loguru import logger
from app.nija_client import CoinbaseClient

logger.info("Starting funded account check...")

# Initialize Coinbase client
try:
    client = CoinbaseClient()
    logger.info("Coinbase client initialized successfully.")
except Exception as e:
    logger.error("Failed to initialize Coinbase client: {}", e)
    raise SystemExit("Cannot continue without Coinbase client")

# Fetch accounts and check balances
try:
    accounts = client.get_accounts()
    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        logger.info(f"Account: {name} | Balance: {amount} {currency}")
        if amount > 0:
            funded_accounts.append((name, amount, currency))

    if funded_accounts:
        logger.success("Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            logger.success(f" - {name}: {amount} {currency}")
    else:
        logger.warning("No funded accounts detected.")

except Exception as e:
    logger.error("Error fetching accounts: {}", e)
