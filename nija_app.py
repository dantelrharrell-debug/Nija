# --- nija_client.py patch ---
import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Try importing CoinbaseClient
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] coinbase_advanced_py import SUCCESS")
except ModuleNotFoundError:
    logger.error("[NIJA] coinbase_advanced_py not installed")
except Exception as e:
    logger.error(f"[NIJA] CoinbaseClient import failed: {e}")

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")  # Or your PEM path
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# Initialize live client
client = None
if CoinbaseClient and API_KEY and API_SECRET and API_PASSPHRASE:
    try:
        client = CoinbaseClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            passphrase=API_PASSPHRASE,
            use_sandbox=False  # live mode
        )
        logger.info("[NIJA] CoinbaseClient LIVE initialized ✅")
    except Exception as e:
        logger.error(f"[NIJA] CoinbaseClient live init FAILED: {e}")
        client = None

# Fallback dummy client if live fails
if client is None:
    class DummyClient:
        def get_account_balance(self, currency="USD"):
            return Decimal(0)
        def place_order(self, **kwargs):
            logger.info(f"[DummyClient] Simulated order {kwargs}")
            return {"status": "simulated"}

    client = DummyClient()
    logger.warning("[NIJA] Using DummyClient ⚠️")

# Helper for balance
def get_usd_balance():
    try:
        return client.get_account_balance("USD")
    except Exception as e:
        logger.error(f"[NIJA] Failed fetching USD balance: {e}")
        return Decimal(0)
