# nija_client.py

import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# --- Coinbase client imports
# -----------------------------
try:
    from coinbase.rest import RESTClient  # for coinbase-advanced-py
except ImportError:
    RESTClient = None
    logger.warning("[NIJA] coinbase-advanced-py RESTClient not found.")

try:
    from coinbase_advancedtrade_python.client import Client as CoinbaseClient
except ImportError:
    CoinbaseClient = None
    logger.warning("[NIJA] coinbase-advancedtrade-python Client not found.")

# -----------------------------
# --- Load Coinbase credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Missing Coinbase API_KEY or API_SECRET in environment")

# -----------------------------
# --- Initialize live client
# -----------------------------
if CoinbaseClient is None:
    raise RuntimeError("❌ No Coinbase client available. Install coinbase-advancedtrade-python or coinbase-advanced-py")

try:
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE,
    )
    logger.info("[NIJA] Coinbase Client initialized ✅")
except Exception as e:
    logger.error(f"❌ Failed to initialize Coinbase Client: {e}")
    raise

# -----------------------------
# --- Expose class
# -----------------------------
CLIENT_CLASS = CoinbaseClient

# -----------------------------
# --- Helper: Get USD balance
# -----------------------------
def get_usd_balance(client_obj=None) -> Decimal:
    client_obj = client_obj or client
    try:
        accounts = client_obj.get_accounts()
        usd_account = next(acc for acc in accounts if acc['currency'] == 'USD')
        return Decimal(usd_account['available'])
    except StopIteration:
        logger.warning("[NIJA] No USD account found")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal(0)

# -----------------------------
# --- Test initialization
# -----------------------------
if __name__ == "__main__":
    balance = get_usd_balance()
    logger.info(f"[NIJA-TEST] USD Balance: {balance}")
