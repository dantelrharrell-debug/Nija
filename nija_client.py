import os
import logging
from decimal import Decimal

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_client")

# --- Import Coinbase REST client ---
try:
    from coinbase.rest import RESTClient
    logger.info("[NIJA] RESTClient imported successfully")
except Exception as e:
    logger.error(f"[NIJA] Could not import RESTClient: {e}")
    raise SystemExit("[NIJA] Live trading cannot run without Coinbase RESTClient")

# --- Load API keys from environment ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional for your account

if not (API_KEY and API_SECRET):
    raise SystemExit("[NIJA] Missing Coinbase API_KEY or API_SECRET. Live trading cannot start.")

# --- Initialize live client ---
try:
    client = RESTClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE  # can be None
    )
    # Quick test
    accounts = client.get_accounts()
    logger.info(f"[NIJA] Coinbase client authenticated. USD balance: {next((a['balance'] for a in accounts if a['currency']=='USD'), '0')}")
except Exception as e:
    raise SystemExit(f"[NIJA] Coinbase authentication failed: {e}")

# --- Helper to get USD balance ---
def get_usd_balance(client):
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.error(f"[NIJA] Could not fetch USD balance: {e}")
    return Decimal("0")
