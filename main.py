import os
import logging
from time import sleep
from flask import Flask, jsonify

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# --- Coinbase Advanced SDK ---
try:
    from coinbase_advanced_py.client import Client
except ImportError:
    logging.error("❌ coinbase-advanced-py not installed. Run `pip install coinbase-advanced-py`")
    raise

# --- Environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # if required

# --- Factory to get Coinbase client ---
def get_coinbase_client():
    if not all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE]):
        logging.error("❌ Missing Coinbase API environment variables")
        raise ValueError("Missing Coinbase API credentials")
    
    try:
        client = Client(
            key=COINBASE_API_KEY,
            secret=COINBASE_API_SECRET,
            passphrase=COINBASE_API_PASSPHRASE,
            sandbox=False  # Set True for sandbox testing
        )
        logging.info("✅ Coinbase client initialized successfully")
        return client
    except Exception as e:
        logging.error(f"❌ Failed to create Coinbase client: {e}")
        raise

# --- Optional test ---
def test_coinbase_connection(client):
    try:
        accounts = client.get_accounts()
        logging.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logging.error(f"❌ Coinbase connection failed: {e}")
        return False

# --- Flask app ---
app = Flask(__name__)
client = get_coinbase_client()
if not test_coinbase_connection(client):
    logging.error("Cannot start bot. Fix Coinbase connection first.")

@app.route("/balances")
def balances():
    accounts = client.get_accounts()
    return jsonify(accounts)

# --- Example trading loop (optional) ---
def run_trading_bot():
    logging.info("⚡ Starting trading bot...")
    while True:
        try:
            accounts = client.get_accounts()
            for acct in accounts:
                logging.info(f"Account: {acct['currency']} | Balance: {acct['balance']['amount']}")
            sleep(10)
        except Exception as e:
            logging.error(f"❌ Error in trading loop: {e}")
            sleep(5)

# Uncomment to run trading loop in main process
# if __name__ == "__main__":
#     run_trading_bot()
