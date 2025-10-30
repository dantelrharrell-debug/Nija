# nija_client.py
import os
import logging
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_client")

# --- Read environment variables (Secret API key flow) ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    logger.error("[NIJA] Missing COINBASE_API_KEY or COINBASE_API_SECRET environment variables.")
    raise SystemExit("[NIJA] Live trading cannot start without API_KEY and API_SECRET.")

# --- Import Coinbase REST client (expected to be available in your environment) ---
try:
    from coinbase.rest import RESTClient
    logger.info("[NIJA] coinbase.rest.RESTClient import OK")
except Exception as e:
    logger.error(f"[NIJA] Could not import RESTClient from coinbase.rest: {e}")
    raise SystemExit("[NIJA] RESTClient import failed — install the correct SDK in requirements.txt")

# --- Initialize REST client (no passphrase) ---
try:
    client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
    # quick verification: fetch accounts
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a.get("currency") == "USD"), Decimal("0"))
    logger.info(f"[NIJA] Coinbase RESTClient authenticated. USD balance: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Coinbase authentication failed: {e}")
    # Helpful hint in logs for the common cause you hit earlier
    logger.error("[NIJA] If you see PEM / MalformedFraming errors, you likely created a PEM/JSON key. Create a Secret/Server API key (simple key+secret) at https://cloud.coinbase.com/access/api and set COINBASE_API_KEY/COINBASE_API_SECRET.")
    raise SystemExit("[NIJA] Authentication failed — fix API credentials and redeploy")

# --- Helper: USD balance fetch ---
def get_usd_balance(client_instance=None):
    """
    Return Decimal USD balance for the given client (defaults to module client).
    """
    if client_instance is None:
        client_instance = client
    try:
        accounts = client_instance.get_accounts()
        for a in accounts:
            if a.get("currency") == "USD":
                return Decimal(a.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA] get_usd_balance error: {e}")
    return Decimal("0")
