import os
import requests
import time
import hmac
import hashlib
import json

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

path = "/v2/accounts"
url = API_BASE + path
timestamp = str(int(time.time()))
message = timestamp + "GET" + path
signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

headers = {
    "CB-ACCESS-KEY": API_KEY,
    "CB-ACCESS-SIGN": signature,
    "CB-ACCESS-TIMESTAMP": timestamp,
    "CB-VERSION": "2025-11-06"
}

response = requests.get(url, headers=headers)
try:
    data = response.json()
except:
    data = {"error": "Invalid response", "raw": response.text}

print(json.dumps(data, indent=4))
