# start_bot.py

# 1️⃣ Add imports and the test function at the very top
import os
import requests
import hmac
import hashlib
import time

def test_coinbase_keys():
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
    BASE_URL = "https://api.coinbase.com/v2"

    if not API_KEY or not API_SECRET:
        print("❌ Missing API_KEY or API_SECRET in environment variables")
        return

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
        "CB-VERSION": "2025-11-11",
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    try:
        r = requests.get(BASE_URL + request_path, headers=headers)
        print("Status Code:", r.status_code)
        print("Response:", r.text)
    except Exception as e:
        print("Exception:", e)

# 2️⃣ Run the test immediately
test_coinbase_keys()

# 3️⃣ Only after confirming keys are valid, import your client
from nija_client import CoinbaseClient

client = CoinbaseClient()  # initialize normally without extra kwargs

import os
import requests
import time
import hmac
import hashlib
from dotenv import load_dotenv

# Load .env automatically
load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional
BASE_URL = "https://api.coinbase.com/v2"

def test_api_keys():
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

    response = requests.get(BASE_URL + request_path, headers=headers)
    print("Status Code:", response.status_code)
    print("Response:", response.text)

if __name__ == "__main__":
    test_api_keys()
