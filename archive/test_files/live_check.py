import logging
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO, format="%(message)s")

def live_confirmation():
    client = CoinbaseClient()  # uses your current LIVE credentials

    logging.info("🔹 Running FULL LIVE confirmation check...")

    # Fetch accounts
    try:
        accounts = client.fetch_accounts()  # returns balances for all accounts
        logging.info("✅ Accounts fetched successfully.\n")
    except Exception as e:
        logging.error(f"❌ Failed to fetch accounts: {e}")
        return

    # Print account balances
    logging.info("=== Account Balances ===")
    for acct in accounts:
        currency = acct['currency']
        balance = float(acct['balance'])
        available = float(acct['available'])
        logging.info(f"{currency}: Balance = {balance}, Available = {available}")
    logging.info("========================\n")

    # Fetch trading pairs
    try:
        pairs = client.fetch_trading_pairs()
        logging.info(f"✅ {len(pairs)} trading pairs available for execution.")
        logging.info("Pairs: " + ", ".join(pairs))
    except Exception as e:
        logging.error(f"❌ Failed to fetch trading pairs: {e}")

    logging.info("\n⚡ LIVE confirmation complete. Bot is ready to trade!")

if __name__ == "__main__":
    live_confirmation()
