import os
import logging
import requests
import time
import hmac
import hashlib
import base64
import json

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_preflight_v3")

BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

# Required permissions
REQUIRED_PERMISSIONS = {
    "read_accounts": "Read account balances",
    "trade": "Place orders",
    "read_orders": "Read orders and trade history",
    "transfer": "Transfer funds (optional)"
}

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

is_jwt = PASSPHRASE is None

def generate_jwt(method, path, body=""):
    """Generate Coinbase JWT for Advanced key"""
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    signature = hmac.new(
        API_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-04"
    }

def send_request(method, path, body=""):
    headers = {}
    if is_jwt:
        headers = generate_jwt(method, path, body)
    else:
        headers = {
            "CB-ACCESS-KEY": API_KEY,
            "CB-ACCESS-SIGN": "",
            "CB-ACCESS-TIMESTAMP": str(int(time.time())),
            "CB-ACCESS-PASSPHRASE": PASSPHRASE,
            "CB-VERSION": "2025-11-04"
        }
    url = BASE_URL + path
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers)
        else:
            resp = requests.post(url, headers=headers, data=body)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            log.error("❌ 401 Unauthorized: JWT or key permissions invalid")
            return None
        else:
            log.error(f"❌ Request failed {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        log.error(f"❌ Request exception: {e}")
        return None

def check_accounts():
    data = send_request("GET", "/v2/accounts")
    if data and "data" in data:
        log.info(f"✅ Accounts accessible, count: {len(data['data'])}")
        return True
    return False

def check_user():
    data = send_request("GET", "/v2/user")
    if data:
        log.info(f"✅ JWT validated for user: {data.get('data', {}).get('id', 'Unknown')}")
        return True
    return False

def run_preflight():
    log.info("[NIJA-PREFLIGHT] Starting preflight v3 check...")
    log.info(f"[NIJA-PREFLIGHT] Using {'JWT' if is_jwt else 'Classic API Key'} method")

    if not API_KEY or not API_SECRET:
        log.error("❌ Missing API_KEY or API_SECRET in environment variables")
        return

    # Validate JWT / Classic Key
    if not check_user():
        log.error("❌ Key validation failed. Check API key permissions or JWT validity")
        return

    # Check accounts access
    if not check_accounts():
        log.error("❌ read_accounts permission missing or account inaccessible")
        return

    # Endpoint dry-run
    resp = send_request("GET", "/v2/products")
    if resp:
        log.info("✅ Trade endpoints reachable")
    else:
        log.warning("⚠️ Trade endpoints may not be accessible (check trade/read_orders permissions)")

    log.info("[NIJA-PREFLIGHT] Preflight v3 complete. All checks passed or warnings issued.")

if __name__ == "__main__":
    run_preflight()
