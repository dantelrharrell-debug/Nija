import os
import requests
import logging
import time
import hmac
import hashlib
import json

log = logging.getLogger("nija_client")
log.setLevel(logging.INFO)

# ---------------------------
# Load API credentials
# ---------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # ignored for Advanced/Base
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([COINBASE_API_KEY, COINBASE_API_SECRET]):
    raise RuntimeError(
        "Missing Coinbase API key/secret. Set COINBASE_API_KEY and COINBASE_API_SECRET."
    )

# ---------------------------
# Helper for signing requests
# ---------------------------
def _sign_request(path, method="GET", body=""):
    timestamp = str(int(time.time()))
    body_str = body if isinstance(body, str) else json.dumps(body) if body else ""
    message = timestamp + method.upper() + path + body_str
    signature = hmac.new(
        COINBASE_API_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return timestamp, signature

# ---------------------------
# Send REST request
# ---------------------------
def _send_request(path, method="GET", body=""):
    timestamp, signature = _sign_request(path, method, body)
    headers = {
        "CB-ACCESS-KEY": COINBASE_API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

    # Only add passphrase if explicitly set (Advanced/Base keys do NOT need it)
    if COINBASE_API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = COINBASE_API_PASSPHRASE

    url = COINBASE_API_BASE + path
    r = requests.request(method, url, headers=headers, data=body)
    
    if r.status_code == 401:
        raise RuntimeError(
            "❌ 401 Unauthorized. Check API key permissions (View + Trade) "
            "and confirm it is an Advanced/Base key."
        )

    r.raise_for_status()
    return r.json()

# ---------------------------
# Fetch all accounts
# ---------------------------
def get_all_accounts():
    try:
        data = _send_request("/v2/accounts")
        return data.get("data", [])
    except Exception as e:
        log.error(f"Failed to fetch accounts: {e}")
        raise RuntimeError(f"Failed to fetch accounts: {e}")

# ---------------------------
# Fetch USD spot balance
# ---------------------------
def get_usd_spot_balance():
    accounts = get_all_accounts()
    for acct in accounts:
        if acct.get("currency") == "USD":
            return float(acct.get("balance", {}).get("amount", 0))
    return 0.0
