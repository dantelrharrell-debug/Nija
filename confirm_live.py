import logging
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)

def live_confirmation():
    client = CoinbaseClient()  # uses your current LIVE credentials

    logging.info("🔹 Running LIVE confirmation check...")

    # Fetch accounts
    try:
        accounts = client.fetch_accounts()  # returns balances for all accounts
        logging.info("✅ Accounts fetched successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to fetch accounts: {e}")
        return

    # Print account balances (mask small details if you want)
    for acct in accounts:
        currency = acct['currency']
        balance = float(acct['balance'])
        available = float(acct['available'])
        logging.info(f"Account: {currency} | Balance: {balance} | Available: {available}")

    # Optional: show trading pairs ready
    try:
        pairs = client.fetch_trading_pairs()  # fetch all pairs your bot can trade
        logging.info(f"✅ {len(pairs)} trading pairs available for execution.")
        logging.info("Pairs: " + ", ".join(pairs))
    except Exception as e:
        logging.error(f"❌ Failed to fetch trading pairs: {e}")

    logging.info("⚡ LIVE confirmation complete. Bot is ready to trade.")

if __name__ == "__main__":
    live_confirmation()
