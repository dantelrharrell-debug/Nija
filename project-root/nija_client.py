import os
import requests
import logging
import time
import hmac
import hashlib
import json

log = logging.getLogger("nija_client")
log.setLevel(logging.INFO)

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([COINBASE_API_KEY, COINBASE_API_SECRET]):
    raise RuntimeError("Missing Coinbase API key/secret. Please set COINBASE_API_KEY and COINBASE_API_SECRET.")

# ---------------------------
# Helper for signing requests
# ---------------------------
def _sign_request(path, method="GET", body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body

    secret_bytes = COINBASE_API_SECRET.encode()
    message_bytes = message.encode()
    signature = hmac.new(secret_bytes, message_bytes, hashlib.sha256).hexdigest()
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
        "Content-Type": "application/json"
    }

    # NOTE: Passphrase header skipped entirely

    url = COINBASE_API_BASE + path
    r = requests.request(method, url, headers=headers, data=body)
    
    if r.status_code == 401:
        log.error("❌ 401 Unauthorized. Your API key may require a passphrase, or permissions are missing.")
        raise RuntimeError("❌ 401 Unauthorized. Check key permissions.")

    r.raise_for_status()
    return r.json()

# ---------------------------
# Fetch all accounts
# ---------------------------
def get_all_accounts():
    try:
        return _send_request("/v2/accounts")["data"]
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
