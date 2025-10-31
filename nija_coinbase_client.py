# at top of nija_coinbase_client.py (or wherever you import the JWT helpers)
import os
import logging

logger = logging.getLogger("nija_coinbase_client")

# REST creds
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

# Only import JWT module if PEM env is present (avoid hard import)
USE_JWT = bool(os.getenv("COINBASE_PEM_KEY") or os.getenv("COINBASE_PEM_KEY_B64"))
if USE_JWT:
    try:
        from nija_coinbase_jwt import get_jwt_token  # only import when needed
        logger.info("[NIJA-CLIENT] JWT module available and will be used as fallback.")
    except Exception as e:
        logger.warning("[NIJA-CLIENT] JWT module import failed: %s", e)
else:
    logger.info("[NIJA-CLIENT] JWT disabled (no PEM env). Using REST key/secret path.")

# nija_coinbase_client.py
import os
import logging
import requests
from decimal import Decimal
from nija_coinbase_jwt import get_jwt_token

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"


def get_usd_balance():
    """
    Fetch USD balance from Coinbase account using JWT auth.
    Returns Decimal(0) if any failure occurs.
    """
    token = None
    try:
        token = get_jwt_token()
    except Exception as e:
        logger.error("[NIJA-CLIENT] Failed to get JWT: %s", e)
        return Decimal(0)

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-10-01"
    }

    try:
        response = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Find USD account
        accounts = data.get("data", [])
        for acct in accounts:
            if acct.get("currency") == "USD":
                balance = Decimal(acct.get("balance", {}).get("amount", "0"))
                logger.info("[NIJA-CLIENT] USD Balance: %s", balance)
                return balance
        logger.warning("[NIJA-CLIENT] No USD account found, returning 0")
        return Decimal(0)

    except Exception as e:
        logger.error("[NIJA-CLIENT] Error fetching USD balance: %s", e)
        return Decimal(0)
