import os
import time
import hmac
import hashlib
import base64
import requests
import json

# Coinbase credentials from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.exchange.coinbase.com")  # Coinbase Pro / Advanced

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise EnvironmentError("HMAC credentials missing! Set API_KEY, API_SECRET, and API_PASSPHRASE.")

# --- Helper functions ---

def _get_headers(method, path, body=""):
    """Generate HMAC headers for Coinbase API."""
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    hmac_key = base64.b64decode(API_SECRET)
    signature = hmac.new(hmac_key, message.encode(), hashlib.sha256)
    signature_b64 = base64.b64encode(signature.digest()).decode()
    return {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# --- Core functions ---

def get_account_balance():
    """Return funded accounts with balances > 0."""
    try:
        path = "/accounts"
        url = BASE_URL + path
        headers = _get_headers("GET", path)
        r = requests.get(url, headers=headers)
        data = r.json()
        # Return only accounts with balance > 0
        return {a['currency']: float(a['balance']) for a in data if float(a['balance']) > 0}
    except Exception as e:
        return {"error": str(e)}

def calculate_position_size(account_balance, percent=2):
    """Calculate position size based on account balance and percent allocation."""
    return account_balance * (percent / 100)

def place_order(account_id, side="buy", size=0, product_id="BTC-USD"):
    """
    Place a market order on Coinbase.
    side: 'buy' or 'sell'
    size: amount in base currency (BTC for BTC-USD)
    product_id: trading pair
    """
    try:
        path = "/orders"
        url = BASE_URL + path
        body = {
            "type": "market",
            "side": side,
            "product_id": product_id,
            "size": str(size)
        }
        body_json = json.dumps(body)
        headers = _get_headers("POST", path, body_json)
        r = requests.post(url, headers=headers, data=body_json)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# --- Debug/Test function ---

def debug_funded_accounts():
    """Print all funded accounts and balances."""
    accounts = get_account_balance()
    if "error" in accounts:
        print("Error:", accounts["error"])
    else:
        print("Funded Accounts:", accounts)
    return accounts
