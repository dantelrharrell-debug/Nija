import os
import logging
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # will be ignored

# --- Attempt import of Coinbase RESTClient ---
try:
    from coinbase.rest import RESTClient
    logger.info("[NIJA] RESTClient imported successfully")
except Exception as e:
    raise SystemExit(f"[NIJA] Cannot import RESTClient: {e}")

# --- Initialize live client ---
if not API_KEY or not API_SECRET:
    raise SystemExit("[NIJA] Missing Coinbase API_KEY or API_SECRET. Cannot start live trading.")

try:
    if API_PASSPHRASE:
        logger.warning("[NIJA] Ignoring API_PASSPHRASE — RESTClient does not use it")

    client = RESTClient(
        api_key=API_KEY,
        api_secret=API_SECRET
    )
    # quick test call
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), Decimal("0"))
    logger.info(f"[NIJA] Coinbase client authenticated. USD balance: {usd_balance}")
except Exception as e:
    raise SystemExit(f"[NIJA] Coinbase authentication failed: {e}")


# --- Helper function ---
def get_usd_balance(client):
    try:
        accounts = client.get_accounts()
        for a in accounts:
            if a.get("currency") == "USD":
                return Decimal(a.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA] Could not fetch USD balance: {e}")
    return Decimal("0")
