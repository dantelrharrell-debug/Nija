import os
import requests
import time
import hmac
import hashlib

# Load API credentials from environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

BASE_URL = "https://api.coinbase.com/v2"

def test_accounts():
    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/accounts"
    body = ""

    # Create Coinbase signature
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

    response = requests.get(BASE_URL + request_path, headers=headers)
    print("Status Code:", response.status_code)
    print("Response:", response.text)

if __name__ == "__main__":
    test_accounts()
