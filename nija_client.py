# nija_client.py
import os
import logging
from decimal import Decimal

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Dummy client fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] Returning fake balances")
        return [{"currency": "USD", "balance": Decimal("1000")}]

# --- Attempt to import Coinbase Exchange client ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    CoinbaseClient = None
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- Load API keys from environment ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# --- Initialize client function ---
def init_client():
    """
    Returns a live Coinbase client if keys are valid, otherwise DummyClient.
    """
    if CoinbaseClient and API_KEY and API_SECRET and API_PASSPHRASE:
        try:
            client = CoinbaseClient(API_KEY, API_SECRET, API_PASSPHRASE)
            # Test credentials quickly
            _ = client.get_accounts()
            logger.info("[NIJA] Coinbase client authenticated")
            return client
        except Exception as e:
            logger.warning(f"[NIJA] Coinbase authentication failed: {e}")
    else:
        logger.warning("[NIJA] Missing Coinbase keys or client unavailable")
    return DummyClient()

# --- Helper to get USD balance safely ---
def get_usd_balance(client):
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
    return Decimal("0")
