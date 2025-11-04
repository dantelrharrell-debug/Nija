import os
import time
import hmac
import hashlib
import base64
import requests

# --------------------------
# Load API credentials
# --------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise RuntimeError("Coinbase API credentials are not fully set in environment variables.")

# --------------------------
# Helper function to generate Coinbase API signature
# --------------------------
def generate_signature(path, method="GET"):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path
    sig = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET), prehash.encode(), hashlib.sha256).digest()
    ).decode()
    return ts, sig

# --------------------------
# Function to get Coinbase accounts
# --------------------------
def get_accounts():
    path = "/v2/accounts"
    ts, sig = generate_signature(path)
    
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
        "Content-Type": "application/json"
    }
    
    try:
        r = requests.get(API_BASE + path, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print("Request failed:", e)
        return None

# --------------------------
# Function to get USD balance
# --------------------------
def get_usd_balance():
    data = get_accounts()
    if not data or "data" not in data:
        print("Failed to fetch account data.")
        return 0.0
    
    for account in data["data"]:
        if account.get("currency") == "USD":
            return float(account.get("balance", {}).get("amount", 0))
    
    print("No USD account found.")
    return 0.0

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    balance = get_usd_balance()
    print(f"USD Balance: ${balance:.2f}")
