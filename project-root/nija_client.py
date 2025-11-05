import os
import time
import hmac
import hashlib
import base64
import requests
import logging

log = logging.getLogger("nija_client")
log.setLevel(logging.INFO)

# -------------------------
# Load Coinbase credentials
# -------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing Coinbase API_KEY or API_SECRET in environment variables")

log.info(f"✅ Coinbase API_KEY present: {bool(API_KEY)}")
log.info(f"✅ Coinbase API_SECRET present: {bool(API_SECRET)}")
log.info(f"⚠️ Coinbase API_PASSPHRASE present: {bool(API_PASSPHRASE)}")


# -------------------------
# Helpers
# -------------------------
def get_timestamp() -> str:
    """Return current UTC timestamp in seconds"""
    return str(int(time.time()))

def sign_request(method: str, path: str, body: str = "") -> dict:
    """Generate Coinbase headers, works with/without passphrase"""
    timestamp = get_timestamp()
    message = f"{timestamp}{method.upper()}{path}{body}"

    # Coinbase allows both hex and base64 signatures, we'll use base64
    signature = hmac.new(
        API_SECRET.encode(), message.encode(), hashlib.sha256
    ).digest()
    signature_b64 = base64.b64encode(signature).decode()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    return headers


# -------------------------
# Core request
# -------------------------
def _send_request(path: str, method="GET", body=""):
    url = f"{BASE_URL}{path}"
    headers = sign_request(method, path, body)

    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, timeout=10)
        elif method.upper() == "POST":
            r = requests.post(url, headers=headers, data=body, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")

        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        log.error(f"❌ Coinbase request failed ({r.status_code}): {r.text}")
        raise RuntimeError(f"Coinbase request failed: {e}") from e
    except Exception as e:
        log.error(f"❌ Request exception: {e}")
        raise


# -------------------------
# Public functions
# -------------------------
def get_all_accounts():
    """Fetch all Coinbase accounts (wallets/balances)"""
    return _send_request("/v2/accounts")


def get_usd_spot_balance():
    """Return USD spot balance as float"""
    accounts_data = get_all_accounts()
    for acct in accounts_data.get("data", []):
        if acct.get("currency") == "USD":
            return float(acct.get("balance", {}).get("amount", 0))
    return 0.0
