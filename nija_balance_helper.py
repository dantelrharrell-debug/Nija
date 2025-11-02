import os
import logging
from decimal import Decimal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from coinbase.rest import RESTClient

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- PEM Validation (optional but recommended) ---
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")

if not PEM_PATH:
    logger.error("[NIJA-BALANCE] COINBASE_API_SECRET_PATH not set")
else:
    if not os.path.exists(PEM_PATH):
        logger.error(f"[NIJA-BALANCE] PEM file not found at: {PEM_PATH}")
    else:
        try:
            with open(PEM_PATH, "rb") as f:
                pem_bytes = f.read()

            private_key = serialization.load_pem_private_key(
                pem_bytes,
                password=None,
                backend=default_backend()
            )
            logger.info("[NIJA-BALANCE] PEM loaded successfully ✅")

        except Exception as e:
            logger.error("[NIJA-BALANCE] Failed to load PEM: %s", e)
            logger.error("Check PEM formatting (no \\n, full base64 content, valid headers).")

# --- Coinbase Client Helper ---
def get_rest_client():
    """
    Lazily initialize RESTClient only when needed.
    Returns None if environment variables are missing.
    """
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        logger.warning("[NIJA-BALANCE] Missing Coinbase API credentials in environment")
        return None

    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        logger.info("[NIJA-BALANCE] Coinbase RESTClient initialized successfully")
        return client
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to initialize Coinbase client: {e}")
        return None


# --- Balance Fetcher ---
def get_usd_balance():
    """
    Fetch the USD balance from Coinbase account.
    Returns Decimal(0) if fetch fails or credentials are missing.
    """
    client = get_rest_client()
    if not client:
        logger.warning("[NIJA-BALANCE] No client available, returning 0")
        return Decimal(0)

    try:
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct["currency"] == "USD":
                balance = Decimal(acct["balance"]["amount"])
                logger.info(f"[NIJA-BALANCE] USD Balance fetched: {balance}")
                return balance
        logger.warning("[NIJA-BALANCE] No USD account found, returning 0")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Error fetching USD balance: {e}")
        return Decimal(0)
