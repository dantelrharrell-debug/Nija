import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

try:
    import coinbase_advanced_py.client as cap
    CoinbaseClient = cap.CoinbaseClient
except Exception as e:
    logger.error(f"[NIJA] CoinbaseClient import failed: {e}")
    raise

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

if not API_KEY or not API_SECRET:
    raise ValueError("[NIJA] Coinbase API credentials missing.")

client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)

def get_usd_balance():
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc['currency'] == 'USD':
                return Decimal(acc['balance']['amount'])
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal(0)

if __name__ == "__main__":
    logger.info(f"[NIJA] Live USD Balance: {get_usd_balance()}")
