import os
import logging
import requests
from decimal import Decimal

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

COINBASE_API_URL = "https://api.coinbase.com/v2/accounts"

def _make_signed_headers(method: str, request_path: str, body: str = "") -> dict:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    api_passphrase = os.getenv("COINBASE_PASSPHRASE", "").strip() or ""

    import time, hmac, hashlib, base64
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + request_path + (body or "")
    signature = hmac.new(api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(signature).decode()

    return {
        "CB-VERSION": "2025-10-01",
        "CB-ACCESS-KEY": api_key,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": api_passphrase,
        "Content-Type": "application/json",
    }

def get_usd_balance() -> Decimal:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        logger.error("[NIJA-CLIENT] Missing API key or secret in environment.")
        return Decimal(0)

    try:
        request_path = "/v2/accounts"
        headers = _make_signed_headers("GET", request_path)
        resp = requests.get(COINBASE_API_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("data", [])

        for acct in accounts:
            if str(acct.get("currency", "")).upper() == "USD":
                balance = Decimal(acct.get("balance", {}).get("amount", "0"))
                logger.info("[NIJA-CLIENT] USD Balance: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0")
        return Decimal(0)

    except requests.exceptions.HTTPError as e:
        logger.error("[NIJA-CLIENT] HTTP error fetching USD balance: %s | %s", e, getattr(e.response, "text", ""))
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
