import os
import base64
import logging
from decimal import Decimal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger("nija_balance_helper")
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)

# --- PEM / Coinbase config ---
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # actual PEM
PEM_B64 = os.getenv("COINBASE_PEM_B64")          # optional base64

def _try_load_pem_bytes(b: bytes):
    """Return (True, None) if load succeeds, (False, err_str) otherwise."""
    try:
        serialization.load_pem_private_key(b, password=None, backend=default_backend())
        return True, None
    except Exception as e:
        return False, str(e)

# --- Verify PEM ---
if PEM_CONTENT:
    ok, err = _try_load_pem_bytes(PEM_CONTENT.encode())
    logger.info("PEM from COINBASE_PEM_CONTENT load_ok=%s", ok)
    if not ok:
        logger.error("COINBASE_PEM_CONTENT load failed: %s", err)
        if "\\n" in PEM_CONTENT:
            logger.error("PEM contains escaped \\n sequences — use real newlines.")

if PEM_B64:
    try:
        dec = base64.b64decode(PEM_B64)
        ok, err = _try_load_pem_bytes(dec)
        logger.info("PEM from COINBASE_PEM_B64 load_ok=%s", ok)
        if not ok:
            logger.error("COINBASE_PEM_B64 load failed: %s", err)
    except Exception as e:
        logger.error("COINBASE_PEM_B64 not valid base64: %s", e)

# --- Balance helper ---
def get_usd_balance(client) -> Decimal:
    """
    Fetch USD balance from a Coinbase client object.
    Returns Decimal(0) on failure.
    """
    if client is None:
        logger.warning("[NIJA-BALANCE] No client provided, returning 0")
        return Decimal("0")

    try:
        # Advanced client style
        if hasattr(client, "fetch_advanced_accounts"):
            accounts = client.fetch_advanced_accounts()
            usd_total = Decimal("0")
            for a in accounts:
                bal = a.get("balance", {})
                if bal.get("currency") in ("USD", "USDC"):
                    usd_total += Decimal(str(bal.get("amount", 0)))
            return usd_total

        # Fallback generic request
        if hasattr(client, "request"):
            status, data = client.request("GET", "/v3/accounts")
            if status == 200 and data:
                usd_total = Decimal("0")
                for a in data.get("data", []):
                    bal = a.get("balance", {})
                    if bal.get("currency") in ("USD", "USDC"):
                        usd_total += Decimal(str(bal.get("amount", 0)))
                return usd_total

    except Exception as e:
        logger.exception("Failed to get USD balance: %s", e)

    return Decimal("0")
