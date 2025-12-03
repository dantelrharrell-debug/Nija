import os
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

PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

def _pem_load_ok(pem_bytes):
    try:
        serialization.load_pem_private_key(pem_bytes, password=None, backend=default_backend())
        return True
    except Exception:
        return False

if PEM_CONTENT:
    ok = _pem_load_ok(PEM_CONTENT.encode())
    logger.info(f"PEM load_ok={ok}")

def get_usd_balance(client) -> Decimal:
    if client is None:
        return Decimal("0")
    try:
        if hasattr(client, "fetch_advanced_accounts"):
            accounts = client.fetch_advanced_accounts()
            for acc in accounts:
                if acc.get("balance", {}).get("currency") in ["USD", "USDC"]:
                    return Decimal(str(acc["balance"]["amount"]))
    except Exception:
        return Decimal("0")
    return Decimal("0")
