import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- Coinbase RESTClient placeholder ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA-BALANCE] Coinbase RESTClient import successful")
except ImportError:
    CoinbaseClient = None
    logger.warning("[NIJA-BALANCE] CoinbaseClient not available, using DummyClient")

# --- PEM setup ---
PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
PEM_B64 = os.getenv("COINBASE_PEM_B64")  # Option A
PEM_DIRECT = os.getenv("COINBASE_PEM_DIRECT")  # Option B

# Write PEM file if not already present
if not os.path.exists(PEM_PATH):
    try:
        if PEM_B64:
            import base64
            with open(PEM_PATH, "wb") as f:
                f.write(base64.b64decode(PEM_B64))
            logger.info("[NIJA-BALANCE] PEM file decoded from base64 (Option A)")
        elif PEM_DIRECT:
            with open(PEM_PATH, "w") as f:
                f.write(PEM_DIRECT)
            logger.info("[NIJA-BALANCE] PEM file written directly (Option B)")
        else:
            logger.error("[NIJA-BALANCE] No PEM provided. Set COINBASE_PEM_B64 or COINBASE_PEM_DIRECT")
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to write PEM file: {e}")

# --- Initialize Coinbase RESTClient ---
def init_client():
    if CoinbaseClient:
        try:
            client = CoinbaseClient(
                key=os.getenv("COINBASE_API_KEY"),
                secret=os.getenv("COINBASE_API_SECRET"),
                passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
                pem_path=PEM_PATH
            )
            return client
        except Exception as e:
            logger.error(f"[NIJA-BALANCE] Failed to initialize CoinbaseClient: {e}")
            return None
    else:
        return None  # or return DummyClient

# --- Fetch USD balance ---
_last_balance_error = None  # Track last error to avoid spam
def get_usd_balance(client):
    global _last_balance_error
    if not client:
        return Decimal(0)
    try:
        accounts = client.get_accounts()
        usd_account = next((a for a in accounts if a['currency'] == 'USD'), None)
        if usd_account:
            return Decimal(usd_account['balance'])
        return Decimal(0)
    except Exception as e:
        # Only log if error changed
        if str(e) != _last_balance_error:
            logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
            _last_balance_error = str(e)
        return Decimal(0)
