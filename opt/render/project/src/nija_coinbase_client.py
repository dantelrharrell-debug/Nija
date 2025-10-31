from nija_coinbase_jwt import get_jwt_token
import requests
from decimal import Decimal
import logging

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def get_usd_balance() -> Decimal:
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
        resp = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for acct in data.get("data", []):
            if str(acct.get("currency", "")).upper() == "USD":
                balance = Decimal(acct.get("balance", {}).get("amount", "0"))
                logger.info("[NIJA-CLIENT] USD Balance: $%s", balance)
                return balance
        return Decimal(0)
    except requests.exceptions.HTTPError as e:
        logger.error("[NIJA-CLIENT] HTTP error fetching USD balance: %s | %s", e, getattr(e.response, "text", ""))
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
