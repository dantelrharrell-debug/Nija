import os
import logging
from time import sleep

# --- Step 1: Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# --- Step 2: Attempt to import Coinbase SDK ---
try:
    from coinbase_advanced.client import Client
except ImportError:
    logging.error("❌ coinbase_advanced package not installed. Run `pip install coinbase-advanced`")
    raise

# --- Step 3: Coinbase client factory ---
def get_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_org_id = os.getenv("COINBASE_ORG_ID")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")

    if not all([api_key, api_secret, api_org_id]):
        raise ValueError("❌ Missing Coinbase credentials in environment variables")

    client = Client(
        api_key=api_key,
        api_secret=api_secret,
        api_org_id=api_org_id,
        pem=pem_content.encode() if pem_content else None
    )
    logging.info("✅ Coinbase client initialized successfully")
    return client

# --- Step 4: Helper to test connection ---
def test_coinbase_connection(client):
    try:
        accounts = client.get_accounts()
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

# --- Step 5: Trading loop (placeholder) ---
def run_trading_bot(client):
    logging.info("⚡ Starting trading bot...")
    while True:
        try:
            accounts = client.get_accounts()
            for acct in accounts:
                logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
            
            # TODO: Insert your trading logic here
            sleep(10)
        except Exception as e:
            logging.error(f"❌ Error in trading loop: {e}")
            sleep(5)

# --- Step 6: Main entry ---
if __name__ == "__main__":
    client = get_coinbase_client()
    if test_coinbase_connection(client):
        run_trading_bot(client)
    else:
        logging.error("Cannot start bot. Fix Coinbase connection first.")
