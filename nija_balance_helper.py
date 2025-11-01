# nija_balance_helper.py
import os
import tempfile
import logging
from coinbase.rest import RESTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- Environment variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM content as string

if not COINBASE_PEM_CONTENT:
    raise ValueError("Set COINBASE_PEM_CONTENT in Render environment variables")

# Write PEM content to a temp file for SDK use
with tempfile.NamedTemporaryFile(delete=False) as tmp_pem_file:
    tmp_pem_file.write(COINBASE_PEM_CONTENT.encode())
    PEM_PATH = tmp_pem_file.name
    logger.info(f"[NIJA-BALANCE] PEM written to temp file: {PEM_PATH}")

# --- Initialize Coinbase client ---
try:
    client = RESTClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        pem_file_path=PEM_PATH  # PEM path is required for this SDK
    )
    logger.info("[NIJA-BALANCE] Coinbase client initialized successfully")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Failed to init Coinbase client: {e}")
    raise

# --- Helper function to get USD balance ---
def get_usd_balance():
    try:
        accounts = client.get_accounts()
        for acc in accounts.data:
            if acc.currency == "USD":
                return float(acc.balance.amount)
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch USD balance: {e}")
    return 0.0
