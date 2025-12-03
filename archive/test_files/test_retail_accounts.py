import os
import time
import hmac
import hashlib
import base64
import requests

# Load your environment variables (make sure these are set in /app/.env)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

def get_accounts():
    method = "GET"
    path = "/v2/accounts"
    url = API_BASE + path
    timestamp = str(int(time.time()))
    body = ""  # GET request has empty body

    message = timestamp + method + path + body
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-08"
    }

    response = requests.get(url, headers=headers)
    return response.status_code, response.json()

# Fetch accounts and print
status, accounts = get_accounts()
if status != 200:
    raise Exception(f"Failed to fetch accounts: {accounts}")

print("Accounts fetched successfully:")
for acct in accounts.get("data", []):
    print(f"{acct['name']} ({acct['currency']}): {acct['balance']['amount']}")
