# nija_coinbase_client.py
import os
import logging
import requests
from decimal import Decimal

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

# --- REST credentials ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

HEADERS = {
    "CB-VERSION": "2025-10-01",
    "Content-Type": "application/json"
}
if API_KEY and API_SECRET:
    HEADERS.update({
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": API_SECRET,  # For simple REST GET auth
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE or ""
    })

def get_usd_balance() -> Decimal:
    """
    Fetch USD balance from Coinbase account using REST keys.
    Returns Decimal(0) if any failure occurs.
    """
    try:
        response = requests.get(COINBASE_API_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        accounts = data.get("data", [])

        # Debug: log full accounts list
        logger.info("[NIJA-CLIENT] Full accounts data: %s", accounts)

        for acct in accounts:
            # Coinbase sometimes returns lowercase, uppercase, or string types
            currency = str(acct.get("currency", "")).upper()
            if currency == "USD":
                balance_str = acct.get("balance", {}).get("amount", "0")
                balance = Decimal(balance_str)
                logger.info("[NIJA-CLIENT] USD Balance: %s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found, returning 0")
        return Decimal(0)

    except Exception as e:
        logger.error("[NIJA-CLIENT] Error fetching USD balance: %s", e)
        return Decimal(0)
