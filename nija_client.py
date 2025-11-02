import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -----------------------------
# --- Attempt to import Coinbase clients
# -----------------------------
RESTClient = None
CoinbaseClient = None

# 1️⃣ Try coinbase-advanced-py (REST)
try:
    from coinbase.rest import RESTClient
    RESTClient = RESTClient
    logger.info("[NIJA] Using coinbase-advanced-py RESTClient ✅")
except ImportError:
    logger.warning("[NIJA] coinbase-advanced-py RESTClient not found ❌")

# 2️⃣ Try coinbase-advancedtrade-python (WebSocket/Advanced)
try:
    from coinbase_advancedtrade_python.client import Client as CoinbaseClient
    logger.info("[NIJA] Using coinbase-advancedtrade-python Client ✅")
except ImportError:
    logger.warning("[NIJA] coinbase-advancedtrade-python Client not found ❌")

# -----------------------------
# --- Load Coinbase credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Missing Coinbase API_KEY or API_SECRET in environment")

# -----------------------------
# --- Initialize client (pick the first available)
# -----------------------------
client = None
CLIENT_CLASS = None

if CoinbaseClient is not None:
    try:
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
        CLIENT_CLASS = CoinbaseClient
        logger.info("[NIJA] Initialized CoinbaseClient (advancedtrade-python) ✅")
    except Exception as e:
        logger.error(f"❌ Failed to initialize CoinbaseClient: {e}")
elif RESTClient is not None:
    try:
        client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
        CLIENT_CLASS = RESTClient
        logger.info("[NIJA] Initialized RESTClient (advanced-py) ✅")
    except Exception as e:
        logger.error(f"❌ Failed to initialize RESTClient: {e}")
else:
    raise RuntimeError("❌ No supported Coinbase client installed. Install coinbase-advancedtrade-python or coinbase-advanced-py")

# -----------------------------
# --- Helper: Get USD balance
# -----------------------------
def get_usd_balance(client_obj=None) -> Decimal:
    client_obj = client_obj or client
    if client_obj is None:
        logger.warning("[NIJA] No client available to fetch USD balance")
        return Decimal(0)

    try:
        if hasattr(client_obj, "get_accounts"):  # REST-like
            accounts = client_obj.get_accounts()
            usd_account = next(acc for acc in accounts if acc['currency'] == 'USD')
            return Decimal(usd_account['available'])
        elif hasattr(client_obj, "get_balances"):  # advancedtrade-python
            balances = client_obj.get_balances()
            return Decimal(balances.get("USD", 0))
        else:
            logger.warning("[NIJA] Client has no method to fetch balances")
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
