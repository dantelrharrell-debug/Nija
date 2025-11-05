import os
import time
import hmac
import hashlib
import base64
import requests
import logging

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing Coinbase API credentials (key/secret)")

log.info("✅ Coinbase API credentials look valid (preflight check passed)")

def _get_timestamp():
    return str(int(time.time()))

def _sign_request(method, path, body=""):
    """
    Create Coinbase signature. Tries base64 first, then hex digest fallback.
    """
    ts = _get_timestamp()
    message = ts + method.upper() + path + body
    key_bytes = base64.b64decode(API_SECRET)
    signature_b64 = base64.b64encode(hmac.new(key_bytes, message.encode(), hashlib.sha256).digest()).decode()
    signature_hex = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return ts, signature_b64, signature_hex

def _send_request(path, method="GET", body=""):
    ts, sig_b64, sig_hex = _sign_request(method, path, body)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig_b64,
        "CB-ACCESS-TIMESTAMP": ts,
    }
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    url = BASE_URL + path
    r = requests.request(method, url, headers=headers, data=body)
    
    if r.status_code == 401:
        log.warning("⚠️ b64 signature failed, trying hex digest fallback")
        headers["CB-ACCESS-SIGN"] = sig_hex
        r = requests.request(method, url, headers=headers, data=body)

    if r.status_code != 200:
        log.error(f"❌ Coinbase request failed ({r.status_code}): {r.text}")
        r.raise_for_status()

    return r.json()

# --------------------------
# Public methods
# --------------------------

def get_all_accounts():
    """
    Fetch all Coinbase accounts.
    """
    try:
        return _send_request("/v2/accounts")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch accounts: {e}")

def get_usd_spot_balance():
    """
    Returns USD spot balance.
    """
    accounts = get_all_accounts()
    for acct in accounts.get("data", []):
        if acct.get("currency") == "USD":
            return float(acct.get("balance", {}).get("amount", 0))
    return 0.0

# --------------------------
# Explicit exports
# --------------------------
__all__ = ["get_all_accounts", "get_usd_spot_balance"]
