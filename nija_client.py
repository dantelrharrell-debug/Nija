# main.py
import os
import logging
from time import sleep

# --- Step 1: Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# --- Step 2: Coinbase client factory ---
try:
    from coinbase_advanced.client import Client
except ImportError:
    logging.error("coinbase_advanced package not installed. Install with `pip install coinbase-advanced`")
    raise

def get_coinbase_client():
    """Return a fully configured Coinbase client."""
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE")
    if not all([api_key, api_secret, api_passphrase]):
        raise ValueError("Missing Coinbase API environment variables.")

    client = Client(
        key=api_key,
        secret=api_secret,
        passphrase=api_passphrase,
        sandbox=False  # True if testing
    )
    logging.info("✅ Coinbase client initialized successfully.")
    return client

# --- Step 3: Helper to verify connection ---
def test_coinbase_connection(client):
    try:
        accounts = client.get_accounts()
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

# --- Step 4: Trading logic placeholder ---
def run_trading_bot(client):
    logging.info("⚡ Starting trading bot...")
    while True:
        try:
            # Example: fetch accounts and balances
            accounts = client.get_accounts()
            for acct in accounts:
                logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
            
            # TODO: Insert your trading strategy logic here
            sleep(10)  # wait 10 sec before next check
        except Exception as e:
            logging.error(f"❌ Error in trading loop: {e}")
            sleep(5)

# --- Step 5: Main entry point ---
if __name__ == "__main__":
    client = get_coinbase_client()
    if test_coinbase_connection(client):
        run_trading_bot(client)
    else:
        logging.error("Cannot start bot. Fix Coinbase connection first.")
