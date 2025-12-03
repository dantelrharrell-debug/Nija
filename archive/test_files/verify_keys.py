import os
import time
import hmac
import hashlib
import requests

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

def get_accounts():
    timestamp = str(int(time.time()))
    method = "GET"
    path = "/v2/accounts"
    message = f"{timestamp}{method}{path}"
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(BASE_URL + path, headers=headers)
        if response.status_code == 200:
            print("✅ API keys are VALID! Accounts:")
            print(response.json())
        else:
            print(f"❌ API call failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Exception occurred: {e}")

if __name__ == "__main__":
    get_accounts()
