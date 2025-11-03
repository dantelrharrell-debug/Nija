#!/usr/bin/env python3
# coinbase_check_balance.py
import os, time, base64, hmac, hashlib, requests, json

API_KEY = os.getenv("COINBASE_API_KEY", "<PUT_KEY_HERE>")
API_SECRET = os.getenv("COINBASE_API_SECRET", "<PUT_SECRET_HERE>")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "<PUT_PASSPHRASE_HERE>")

# Use the Coinbase V2 accounts path
METHOD = "GET"
REQUEST_PATH = "/v2/accounts"
BODY = ""  # GET -> empty body
TIMESTAMP = str(int(time.time()))

def make_signature(secret, timestamp, method, request_path, body):
    # secret provided by Coinbase is base64; decode it first
    try:
        secret_bytes = base64.b64decode(secret)
    except Exception as e:
        raise RuntimeError("Failed to base64-decode API secret: " + str(e))

    prehash = timestamp + method.upper() + request_path + body
    digest = hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    return signature

def fetch_accounts():
    signature = make_signature(API_SECRET, TIMESTAMP, METHOD, REQUEST_PATH, BODY)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": TIMESTAMP,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json",
    }
    url = "https://api.coinbase.com" + REQUEST_PATH
    resp = requests.get(url, headers=headers, timeout=10)
    try:
        print("HTTP", resp.status_code)
        print(resp.text)
    except Exception:
        print("Response not JSON")
    return resp

if __name__ == "__main__":
    if "<PUT_KEY_HERE>" in API_KEY:
        print("Warning: no API_KEY in env. Set COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE or edit file.")
    r = fetch_accounts()
    if r.status_code == 200:
        data = r.json()
        # Print the wallets Coinbase returned (name, currency, amount)
        for acct in data.get("data", []):
            bal = acct.get("balance", {})
            print(f"{acct.get('name')} — {bal.get('amount')} {bal.get('currency')}")
