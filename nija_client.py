# nija_client.py
import os
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -------------------------
# Environment variables
# -------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
PEM_B64 = os.getenv("COINBASE_PEM_B64")

# -------------------------
# Ensure PEM file exists
# -------------------------
if PEM_B64:
    try:
        pem_bytes = base64.b64decode(PEM_B64)
        os.makedirs(os.path.dirname(PEM_PATH), exist_ok=True)
        with open(PEM_PATH, "wb") as f:
            f.write(pem_bytes)
        logger.info(f"[NIJA] PEM file written to {PEM_PATH}")
    except Exception as e:
        logger.error(f"[NIJA] Failed to write PEM file: {e}")

# -------------------------
# Coinbase RESTClient init
# -------------------------
CoinbaseClient = None
try:
    from coinbase.rest import RESTClient
    if API_KEY and API_SECRET:
        CoinbaseClient = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("[NIJA] Coinbase RESTClient initialized successfully")
    else:
        logger.warning("[NIJA] Missing API_KEY or API_SECRET, using DummyClient")
except Exception as e:
    logger.warning(f"[NIJA] Coinbase RESTClient not available: {e}")

# -------------------------
# Dummy client fallback
# -------------------------
class DummyClient:
    def __init__(self):
        logger.warning("[NIJA] Using DummyClient. Trades/balance will be simulated.")

    def get_account(self, currency="USD"):
        return {"balance": 0.0}

if not CoinbaseClient:
    CoinbaseClient = DummyClient()

# -------------------------
# Helper: fetch USD balance
# -------------------------
def get_usd_balance(client):
    try:
        account = client.get_account("USD")
        return float(account.get("balance", 0))
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return 0.0

# -------------------------
# Export client and balance helper
# -------------------------
client = CoinbaseClient
get_balance = lambda: get_usd_balance(client)
