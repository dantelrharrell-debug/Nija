import logging
import requests
from decimal import Decimal
from nija_coinbase_jwt import get_jwt_token

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
        logger.info("[NIJA-CLIENT] Fetching USD balance via Coinbase REST API (JWT)...")
        resp = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("data", [])

        for acct in accounts:
            if str(acct.get("currency", "")).upper() == "USD":
                balance_str = acct.get("balance", {}).get("amount", "0")
                balance = Decimal(balance_str)
                logger.info("[NIJA-CLIENT] USD Balance: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0.")
        return Decimal(0)

    except requests.exceptions.HTTPError as e:
        logger.error("[NIJA-CLIENT] HTTP error fetching USD balance: %s | body=%s", e, getattr(e.response, "text", ""))
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
