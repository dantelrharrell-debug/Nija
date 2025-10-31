# nija_coinbase_client.py (rollback - REST HMAC only)
import os
import logging
import requests
import time
import hmac
import hashlib
import base64
from decimal import Decimal

logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

COINBASE_API_BASE = "https://api.coinbase.com"
COINBASE_API_PATH_ACCOUNTS = "/v2/accounts"
COINBASE_API_URL = COINBASE_API_BASE + COINBASE_API_PATH_ACCOUNTS

def _make_signed_headers(method: str, request_path: str, body: str = "") -> dict:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    api_passphrase = os.getenv("COINBASE_PASSPHRASE", "").strip() or ""

    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + request_path + (body or "")

    # Most Coinbase REST secrets are ascii string -> use utf-8 bytes
    try:
        secret_bytes = api_secret.encode("utf-8")
    except Exception:
        secret_bytes = None

    # compute signature
    signature = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(signature).decode()

    # mask key for logs
    key_fp = (api_key[:6] + "..." + api_key[-6:]) if api_key else "<missing>"

    headers = {
        "CB-VERSION": "2025-10-01",
        "CB-ACCESS-KEY": api_key,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": api_passphrase,
        "Content-Type": "application/json",
    }

    logger.info("[NIJA-CLIENT] Prepared signed headers (key=%s passphrase_set=%s)", key_fp, bool(api_passphrase))
    return headers

def get_usd_balance() -> Decimal:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        logger.error("[NIJA-CLIENT] Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment.")
        return Decimal(0)

    try:
        request_path = COINBASE_API_PATH_ACCOUNTS
        headers = _make_signed_headers("GET", request_path, "")
        logger.info("[NIJA-CLIENT] Fetching USD balance via Coinbase REST API (signed)...")

        resp = requests.get(COINBASE_API_BASE + request_path, headers=headers, timeout=10)

        # log body on error for diagnosis
        if resp.status_code >= 400:
            preview = resp.text[:1000] if resp.text else "<empty>"
            logger.error("[NIJA-CLIENT] Coinbase returned HTTP %s. Body preview: %s", resp.status_code, preview)

        resp.raise_for_status()

        data = resp.json()
        accounts = data.get("data", [])

        for acct in accounts:
            currency = str(acct.get("currency", "")).upper()
            if currency == "USD":
                balance_str = acct.get("balance", {}).get("amount", "0")
                balance = Decimal(str(balance_str).strip())
                logger.info("[NIJA-CLIENT] USD Balance Detected: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0.")
        return Decimal(0)

    except requests.exceptions.HTTPError as e:
        resp = getattr(e, "response", None)
        body = None
        try:
            body = resp.text if resp is not None else None
        except Exception:
            body = "<unreadable body>"
        logger.error("[NIJA-CLIENT] HTTP error fetching USD balance: %s | body=%s", e, body)
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
