import os
import logging
from decimal import Decimal
from coinbase.rest import RESTClient  # live client only

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_client")

# --- Load API keys from environment ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

if not API_KEY or not API_SECRET:
    logger.error("[NIJA] Missing Coinbase API_KEY or API_SECRET. Cannot start live trading.")
    raise RuntimeError("Coinbase API_KEY and API_SECRET are required for live trading.")

# --- Initialize live client ---
def init_client():
    try:
        client = RESTClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            api_passphrase=API_PASSPHRASE  # can be None
        )
        # quick test: fetch account balances
        accounts = client.get_accounts()
        logger.info(f"[NIJA] RESTClient authenticated successfully. Accounts: {accounts}")
        return client
    except Exception as e:
        logger.error(f"[NIJA] RESTClient authentication failed: {e}")
        raise RuntimeError("Cannot start live trading without valid Coinbase client.")

# --- Helper: Get USD balance ---
def get_usd_balance(client):
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
        return Decimal("0")

# --- Initialize client on module load ---
client = init_client()
logger.info(f"[NIJA] Live client initialized. USD balance: {get_usd_balance(client)}")
