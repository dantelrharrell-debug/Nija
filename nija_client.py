# nija_client.py
import os
import time
import logging
from coinbase_advanced_py import Coinbase

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# -----------------------------
# Coinbase client initialization
# -----------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    logging.error("❌ ERROR: Coinbase API keys not set!")
    raise SystemExit("Coinbase API keys are required to run the bot.")

client = Coinbase(
    api_key=COINBASE_API_KEY,
    api_secret=COINBASE_API_SECRET,
    passphrase=COINBASE_API_PASSPHRASE
)

logging.info("✅ Coinbase client initialized successfully.")


# -----------------------------
# Example trading loop
# -----------------------------
def start_trading():
    logging.info("🌟 Starting trading loop...")
    try:
        while True:
            # Example: Fetch account balances
            accounts = client.get_accounts()
            for account in accounts:
                logging.info(f"Account: {account['currency']} - Balance: {account['balance']['amount']}")
            
            # Add your trading logic here
            
            time.sleep(10)  # wait 10 seconds before next check
    except KeyboardInterrupt:
        logging.info("🛑 Trading stopped by user.")
    except Exception as e:
        logging.exception(f"❌ Trading loop error: {e}")
