import os
import logging

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# -----------------------------
# Coinbase client import
# -----------------------------
try:
    from coinbase_advanced.client import Client
    logging.info("Imported coinbase_advanced.Client successfully")
    LIVE_TRADING_ENABLED = True
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")
    LIVE_TRADING_ENABLED = False

# -----------------------------
# Load API credentials from environment variables
# -----------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")  # optional

if LIVE_TRADING_ENABLED:
    if not COINBASE_API_KEY or not COINBASE_API_SECRET:
        logging.error("API credentials missing. Live trading disabled.")
        LIVE_TRADING_ENABLED = False
    else:
        client = Client(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            api_sub=COINBASE_API_SUB
        )
        logging.info("Coinbase client initialized successfully")

# -----------------------------
# Example function: fetch balances
# -----------------------------
def get_account_balances():
    if not LIVE_TRADING_ENABLED:
        logging.warning("Live trading disabled, cannot fetch balances")
        return
    try:
        accounts = client.get_accounts()
        for account in accounts:
            print(f"{account['currency']}: {account['balance']['amount']}")
    except Exception as e:
        logging.error(f"Failed to fetch balances: {e}")

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    logging.info("Bot started")
    logging.info(f"Live trading enabled: {LIVE_TRADING_ENABLED}")
    get_account_balances()
