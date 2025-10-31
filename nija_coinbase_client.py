# nija_coinbase_client.py
import os
import logging
import requests
import time
import hmac
import hashlib
import base64
from decimal import Decimal
from typing import Dict

# --- Logging ---
logger = logging.getLogger("nija_coinbase_client")
logger.setLevel(logging.INFO)

# If you want more verbose debugging temporarily, set NIJA_CLIENT_DEBUG env to "1"
DEBUG = os.getenv("NIJA_CLIENT_DEBUG", "0") == "1"
if DEBUG:
    logger.setLevel(logging.DEBUG)

COINBASE_API_BASE = "https://api.coinbase.com"
COINBASE_API_PATH_ACCOUNTS = "/v2/accounts"
COINBASE_API_URL = COINBASE_API_BASE + COINBASE_API_PATH_ACCOUNTS


def _make_signed_headers(method: str, request_path: str, body: str = "") -> Dict[str, str]:
    """
    Create Coinbase API signed headers for REST API key authentication.
    Uses HMAC-SHA256 of: timestamp + METHOD + request_path + body
    Returns headers dict ready for requests.get/post.
    """
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    api_passphrase = os.getenv("COINBASE_PASSPHRASE", "").strip() or ""

    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + request_path + (body or "")

    # Most Coinbase REST secrets are ASCII strings; treat as bytes
    secret_bytes = api_secret.encode("utf-8")
    signature = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(signature).decode()

    headers = {
        "CB-VERSION": "2025-10-01",
        "CB-ACCESS-KEY": api_key,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": api_passphrase,
        "Content-Type": "application/json",
    }

    if DEBUG:
        # Mask secret/signature in debug logs
        api_key_fp = (api_key[:6] + "..." + api_key[-6:]) if api_key else "<missing>"
        logger.debug("[NIJA-DEBUG] make_signed_headers: key=%s timestamp=%s passphrase_set=%s",
                     api_key_fp, timestamp, bool(api_passphrase))
        # show signature length only (not value)
        logger.debug("[NIJA-DEBUG] signature length: %d", len(signature))
    return headers


def get_usd_balance() -> Decimal:
    """
    Fetch USD balance from Coinbase account using REST-style API key signing.
    Returns Decimal(0) if any failure occurs.
    """
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        logger.error("[NIJA-CLIENT] Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment.")
        return Decimal(0)

    try:
        request_path = COINBASE_API_PATH_ACCOUNTS  # "/v2/accounts"
        headers = _make_signed_headers("GET", request_path, "")
        logger.info("[NIJA-CLIENT] Fetching USD balance via Coinbase REST API (signed)...")

        resp = requests.get(COINBASE_API_BASE + request_path, headers=headers, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        accounts = data.get("data", [])
        if DEBUG:
            logger.debug("[NIJA-CLIENT] Full accounts payload: %s", accounts)

        for acct in accounts:
            # Coinbase may use lowercase/uppercase for currency field; normalize
            currency = str(acct.get("currency", "")).upper()
            if currency == "USD":
                # Coinbase account balance shape: acct["balance"] = {"amount": "10.30", "currency": "USD"}
                balance_str = acct.get("balance", {}).get("amount", "0")
                # Defensive: strip any whitespace
                balance = Decimal(str(balance_str).strip())
                logger.info("[NIJA-CLIENT] USD Balance Detected: $%s", balance)
                return balance

        logger.warning("[NIJA-CLIENT] No USD account found — returning 0.")
        return Decimal(0)

    except requests.exceptions.HTTPError as e:
        # Log HTTP status + any body text to help debug 401/403
        resp = getattr(e, "response", None)
        body = None
        try:
            body = resp.text if resp is not None else None
        except Exception:
            body = "<unreadable body>"
        logger.error("[NIJA-CLIENT] Network error fetching USD balance: %s %s", e, body)
        return Decimal(0)
    except requests.exceptions.RequestException as e:
        logger.error("[NIJA-CLIENT] Network/timeout error fetching USD balance: %s", e)
        return Decimal(0)
    except Exception as e:
        logger.error("[NIJA-CLIENT] Unexpected error fetching USD balance: %s", e)
        return Decimal(0)
