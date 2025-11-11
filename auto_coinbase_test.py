import os
import requests
import time
import hmac
import hashlib

# Load API credentials from environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

# Possible endpoints
ENDPOINTS = {
    "live": "https://api.coinbase.com/v2",
    "sandbox": "https://api-public.sandbox.coinbase.com/v2"
}

def test_accounts(base_url):
    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/accounts"
    body = ""

    message = timestamp + method + request_path + body
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-11"
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    response = requests.get(base_url + request_path, headers=headers)
    return response.status_code, response.text

if __name__ == "__main__":
    for name, url in ENDPOINTS.items():
        print(f"\nTesting {name} endpoint: {url}")
        status, data = test_accounts(url)
        print("Status Code:", status)
        print("Response:", data)
        if status == 200:
            print(f"✅ Success: {name} keys are valid!")
            break
        elif status == 401:
            print(f"❌ Unauthorized: {name} keys are invalid or lack permissions.")
