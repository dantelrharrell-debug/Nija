# nija_balance_helper.py
import os
import tempfile
import logging
from coinbase.rest import RESTClient  # make sure coinbase-sdk installed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")

# --- Load keys from environment ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY", "your_api_key_here")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET", "your_api_secret_here")
COINBASE_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "your_passphrase_here")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # full PEM with BEGIN/END lines

if not COINBASE_PEM_CONTENT:
    logger.error("[NIJA-BALANCE] PEM content missing!")
    raise ValueError("Set COINBASE_PEM_CONTENT in Render environment variables")

# --- Write PEM to a temporary file ---
with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
    f.write(COINBASE_PEM_CONTENT)
    PEM_PATH = f.name
    logger.info(f"[NIJA-BALANCE] PEM written to temp file: {PEM_PATH}")

# --- Initialize Coinbase client ---
try:
    client = RESTClient(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        passphrase=COINBASE_PASSPHRASE,
        pem_file_path=PEM_PATH  # some SDKs need PEM path
    )
    logger.info("[NIJA-BALANCE] Coinbase client initialized ✅")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Failed to init Coinbase client: {e}")
    raise

# --- Fetch USD balance ---
def get_usd_balance() -> float:
    try:
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct.balance.currency == "USD":
                balance = float(acct.balance.amount)
                logger.info(f"[NIJA-BALANCE] USD Balance: ${balance}")
                return balance
        logger.warning("[NIJA-BALANCE] USD account not found")
        return 0.0
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch balance: {e}")
        return 0.0

# --- Optional: Test fetch on import ---
if __name__ == "__main__":
    get_usd_balance()
