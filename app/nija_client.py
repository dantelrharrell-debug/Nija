import os
import logging
from time import sleep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# --- Import Coinbase SDK ---
try:
    from coinbase_advanced.client import Client
except ImportError:
    logging.error("❌ coinbase_advanced not installed. Install via start.sh")
    raise


# --- Create Coinbase Client ---
def get_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_org_id = os.getenv("COINBASE_ORG_ID")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")

    if not api_key or not api_secret or not api_org_id:
        raise ValueError("❌ Missing required Coinbase environment variables")

    client = Client(
        api_key=api_key,
        api_secret=api_secret,
        api_org_id=api_org_id,
        pem=pem_content.encode() if pem_content else None
    )

    logging.info("✅ Coinbase client initialized")
    return client


# --- Test Coinbase ---
def test_coinbase_connection(client):
    try:
        accounts = client.get_accounts()
        logging.info(f"✅ Connection OK. Accounts: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Connection FAILED: {e}")
        return False


# --- Trading Bot Loop ---
def run_trading_bot(client):
    logging.info("⚡ Trading bot started...")
    while True:
        try:
            accounts = client.get_accounts()
            for acct in accounts:
                logging.info(
                    f"{acct['currency']} Balance: {acct['balance']['amount']}"
                )
            sleep(10)
        except Exception as e:
            logging.error(f"❌ Trading loop error: {e}")
            sleep(5)


# --- Main Entry ---
if __name__ == "__main__":
    client = get_coinbase_client()

    if test_coinbase_connection(client):
        run_trading_bot(client)
    else:
        logging.error("❌ Cannot start bot. Fix Coinbase connection first.")
