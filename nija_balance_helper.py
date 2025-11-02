# nija_balance_helper.py
import os
import logging
import base64
from decimal import Decimal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- Step 0: config ---
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")   # optional: the whole PEM with real newlines
PEM_B64 = os.getenv("COINBASE_PEM_B64")           # optional: base64-encoded PEM

private_key = None

def load_pem_from_path(path: str):
    try:
        if not os.path.exists(path):
            logger.debug(f"[NIJA-BALANCE] PEM path does not exist: {path}")
            return None
        with open(path, "rb") as f:
            data = f.read()
        return serialization.load_pem_private_key(data, password=None, backend=default_backend())
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] load_pem_from_path failed: {e}")
        return None

def load_pem_from_raw(pem_str: str):
    try:
        data = pem_str.encode()
        return serialization.load_pem_private_key(data, password=None, backend=default_backend())
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] load_pem_from_raw failed: {e}")
        return None

def load_pem_from_b64(b64_str: str):
    try:
        data = base64.b64decode(b64_str)
        return serialization.load_pem_private_key(data, password=None, backend=default_backend())
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] load_pem_from_b64 failed: {e}")
        return None

# --- Try path first (preferred) ---
if PEM_PATH:
    logger.info(f"[NIJA-BALANCE] Trying PEM path: {PEM_PATH}")
    private_key = load_pem_from_path(PEM_PATH)

# --- Fall back to raw env var ---
if private_key is None and PEM_CONTENT:
    logger.info("[NIJA-BALANCE] Trying PEM from COINBASE_PEM_CONTENT env var")
    private_key = load_pem_from_raw(PEM_CONTENT)

# --- Fall back to base64 env var ---
if private_key is None and PEM_B64:
    logger.info("[NIJA-BALANCE] Trying PEM from COINBASE_PEM_B64 env var (base64)")
    private_key = load_pem_from_b64(PEM_B64)

if private_key:
    logger.info("[NIJA-BALANCE] PEM loaded successfully ✅")
else:
    logger.warning("[NIJA-BALANCE] No valid PEM loaded. Coinbase client may fall back to simulated mode.")

# --- Coinbase client / balance helper (example) ---
def get_rest_client():
    from coinbase.rest import RESTClient  # local import so app can still start without coinbase lib installed
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        logger.warning("[NIJA-BALANCE] Missing API key/secret in env")
        return None
    try:
        # RESTClient typically needs api_key, api_secret, and possibly private key handling inside the library.
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized (credentials present)")
        return client
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to init RESTClient: {e}")
        return None

def get_usd_balance():
    client = get_rest_client()
    if not client:
        return Decimal(0)
    try:
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct.get("currency") == "USD":
                return Decimal(acct["balance"]["amount"])
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
    return Decimal(0)
