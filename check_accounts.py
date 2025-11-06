import os
import time
import hmac
import hashlib
import base64
import requests
import json

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
BASE_URL = "https://api.coinbase.com"

def get_accounts():
    method = "GET"
    path = "/v2/accounts"
    timestamp = str(int(time.time()))
    message = timestamp + method + path
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
    }

    response = requests.get(BASE_URL + path, headers=headers)
    return response.json()

accounts = get_accounts()
print(json.dumps(accounts, indent=2))
