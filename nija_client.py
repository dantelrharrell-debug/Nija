# -----------------------------
# nija_client.py
# -----------------------------
import os
import logging
from decimal import Decimal
from coinbase_advancedtrade_python.client import Client as CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# Read API credentials from environment
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional if your key uses passphrase

if not (API_KEY and API_SECRET):
    logger.error("[NIJA] Missing Coinbase API credentials! Cannot run live.")
    raise SystemExit("[NIJA] Fix credentials before running.")

# -----------------------------
# Initialize Coinbase client
# -----------------------------
try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
    logger.info("[NIJA] Coinbase client initialized successfully.")
except Exception as e:
    logger.error(f"[NIJA] Failed to initialize Coinbase client: {e}")
    raise SystemExit("[NIJA] Cannot start bot without valid Coinbase client.")

# -----------------------------
# Helper function: get USD balance
# -----------------------------
def get_usd_balance() -> Decimal:
    try:
        accounts = client.get_accounts()
        for acct in accounts['data']:
            if acct['currency'] == 'USD':
                return Decimal(acct['available'])
        return Decimal("0")
    except Exception as e:
        logger.error(f"[NIJA] Error fetching USD balance: {e}")
        return Decimal("0")
