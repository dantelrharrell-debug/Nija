import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # for Standard API
BASE_ADVANCED = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
BASE_STANDARD = os.getenv("COINBASE_STANDARD_BASE", "https://api.pro.coinbase.com")

if not API_KEY or not API_SECRET:
    raise Exception("API_KEY or API_SECRET not set")


class CoinbaseClient:
    def __init__(self):
        self.client_type = None
        self.base_url = None

        # Try Advanced API first
        if self._test_advanced():
            self.client_type = "advanced"
            self.base_url = BASE_ADVANCED
            print("[CoinbaseClient] Using Advanced API")
        # Then fallback to Standard API
        elif self._test_standard():
            self.client_type = "standard"
            self.base_url = BASE_STANDARD
            print("[CoinbaseClient] Using Standard API")
        else:
            raise Exception("No valid Coinbase API found. Check your keys.")

    def _test_advanced(self):
        try:
            endpoint = "/v2/accounts"
            url = BASE_ADVANCED + endpoint
            timestamp = str(int(time.time()))
            message = timestamp + 'GET' + endpoint
            signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers = {
                "CB-ACCESS-KEY": API_KEY,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
            }
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def _test_standard(self):
        try:
            endpoint = "/accounts"
            url = BASE_STANDARD + endpoint
            timestamp = str(int(time.time()))
            method = 'GET'
            body = ""
            message = timestamp + method + endpoint + body
            signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers = {
                "CB-ACCESS-KEY": API_KEY,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": API_PASSPHRASE or "",
            }
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def get_accounts(self):
        if self.client_type == "advanced":
            endpoint = "/v2/accounts"
        else:
            endpoint = "/accounts"

        url = self.base_url + endpoint
        timestamp = str(int(time.time()))
        method = "GET"
        body = ""
        if self.client_type == "advanced":
            message = timestamp + method + endpoint
            signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers = {
                "CB-ACCESS-KEY": API_KEY,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
            }
        else:
            message = timestamp + method + endpoint + body
            signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers = {
                "CB-ACCESS-KEY": API_KEY,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": API_PASSPHRASE or "",
            }

        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f"API request failed: {resp.status_code} {resp.text}")
        return resp.json()
