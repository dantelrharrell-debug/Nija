# nija_coinbase_client.py
import os
import logging
import requests
from decimal import Decimal

# --- Setup logging ---
logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

# --- Coinbase REST API ---
COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def get_usd_balance() -> Decimal:
    """
    Fetch USD balance from Coinbase account using API key authentication.
    Returns Decimal(0) if fetch fails.
    """
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        logger.error("[NIJA-CLIENT] Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment.")
        return Decimal(0)

    headers = {
        "CB-VERSION": "2025-10-01",
        "Authorization": f"Bearer {api_key.strip()}"
    }

    try:
        logger.info("[NIJA-CLIENT] Fetching USD balance via Coinbase REST API...")
        response = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        accounts = data.get("data", [])
        if not accounts:
            logger.warning("[NIJA-CLIENT] No account data returned.")
            return Decimal(0)

        for acct in accounts:
            currency = str(acct.get("currency", "")).upper()
            if currency == "USD":
                balance_str = acct.get("balance", {}).get("amount", "0")
                balance = Decimal(balance_str)
                logger.info("[NIJA-CLIENT] USD Balance Detected: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0.")
        return Decimal(0)

    except requests.exceptions.RequestException as e:
        logger.error("[NIJA-CLIENT] Network error fetching USD balance: %s", e)
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
