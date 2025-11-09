import os
import time
import hmac
import hashlib
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.session = requests.Session()
        self.session.headers.update({
            "CB-ACCESS-KEY": self.api_key,
            "Content-Type": "application/json"
        })
        logger.info("HMAC CoinbaseClient initialized.")

    def sign_request(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-SIGN": signature
        }

    def request(self, method, path, **kwargs):
        try:
            body = kwargs.get("data", "") or ""
            headers = self.sign_request(method, path, body)
            headers.update(kwargs.get("headers", {}))
            response = self.session.request(method, self.base + path, headers=headers, **kwargs)

            try:
                return response.status_code, response.json()
            except Exception:
                logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
                return response.status_code, None
        except Exception as e:
            logger.exception(f"❌ HTTP request failed: {e}")
            return None, None

def fetch_hmac_accounts():
    client = CoinbaseClient()
    status, accounts = client.request(method="GET", path="/v3/accounts")  # <-- v3 endpoint
    if status != 200 or not accounts:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []
    return accounts
