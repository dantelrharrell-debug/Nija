# nija_coinbase_client.py
import requests
import logging
from decimal import Decimal
from nija_coinbase_jwt import get_jwt_token

logger = logging.getLogger("nija_coinbase_client")

COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def get_usd_balance():
    try:
        jwt_token = get_jwt_token()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "CB-VERSION": "2023-10-31",
        }
        response = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        for account in data.get("data", []):
            if account.get("currency") == "USD":
                balance = Decimal(account.get("balance", {}).get("amount", "0"))
                logger.info(f"[NIJA-CLIENT] USD balance: ${balance}")
                return balance
        logger.warning("[NIJA-CLIENT] USD account not found")
        return Decimal(0)
    except requests.HTTPError as e:
        logger.error(f"[NIJA-CLIENT] HTTP error fetching USD balance: {e} | body={e.response.text}")
        return Decimal(0)
    except Exception as e:
        logger.error(f"[NIJA-CLIENT] Error fetching USD balance: {e}")
        return Decimal(0)
