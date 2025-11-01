# nija_balance_helper.py
import os
import tempfile
import logging
from decimal import Decimal
from coinbase.rest import RESTClient  # ensure this matches your coinbase client

logger = logging.getLogger("nija_balance_helper")

# --- Load PEM content from environment variable ---
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not PEM_CONTENT:
    logger.error("[NIJA-BALANCE] PEM content missing! Aborting balance fetch.")

def write_pem_temp_file():
    """
    Write PEM content to a temporary file and return its path.
    """
    if not PEM_CONTENT:
        return None
    try:
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        tmp_file.write(PEM_CONTENT.encode())  # write string as bytes
        tmp_file.flush()
        tmp_file.close()
        logger.info("[NIJA-BALANCE] PEM content written to temporary file ✅")
        return tmp_file.name
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to write PEM file: {e}")
        return None

def get_usd_balance() -> Decimal:
    """
    Fetch USD balance from Coinbase account using RESTClient.
    Returns Decimal('0') if fetch fails.
    """
    pem_path = write_pem_temp_file()
    if not pem_path:
        logger.error("[NIJA-BALANCE] No PEM file available, returning 0 balance.")
        return Decimal("0")

    try:
        # Initialize client with PEM path (adjust if your SDK needs key/secret differently)
        client = RESTClient(key=None, secret=pem_path)
        accounts = client.get_accounts()
        for acct in accounts.data:
            if acct.currency == "USD":
                balance = Decimal(acct.balance.amount)
                logger.info(f"[NIJA-BALANCE] USD balance fetched: {balance}")
                return balance
        return Decimal("0")
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to fetch balance: {e}")
        return Decimal("0")
