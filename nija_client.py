# nija_client.py
import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Import CoinbaseClient properly ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.error("[NIJA] coinbase_advanced_py not installed or not found. Live trading will fail.")
    raise
except ImportError as e:
    logger.error(f"[NIJA] Failed importing CoinbaseClient: {e}")
    raise

# --- Load API credentials from environment ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

if not API_KEY or not API_SECRET:
    logger.error("[NIJA] Coinbase API key or secret missing in environment variables.")
    raise ValueError("Missing Coinbase API credentials")

# --- Initialize live client ---
client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)

# --- Helper to fetch USD balance ---
def get_usd_balance():
    """
    Fetch USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails.
    """
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc['currency'] == 'USD':
                balance = Decimal(acc['balance']['amount'])
                return balance
        logger.warning("[NIJA] No USD account found.")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal(0)

# --- Optional: quick test ---
if __name__ == "__main__":
    balance = get_usd_balance()
    logger.info(f"[NIJA] Live USD Balance: {balance}")
