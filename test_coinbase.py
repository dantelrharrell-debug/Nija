import os
import requests
from requests.auth import AuthBase
import hmac
import hashlib
import time
import base64

# Load from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # if required by your client

BASE_URL = "https://api.coinbase.com/v2"

def get_accounts():
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
        "CB-VERSION": "2025-11-11",  # can set current date
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    response = requests.get(BASE_URL + request_path, headers=headers)
    return response.status_code, response.text

if __name__ == "__main__":
    status, data = get_accounts()
    print("Status Code:", status)
    print("Response:", data)
