# nija_hmac_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret must be set in environment variables")
        logger.info("✅ Coinbase HMAC client initialized")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    def request(self, method="GET", path="/v3/accounts", body=""):
        url = self.base + path
        headers = self._get_headers(method, path, body)
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            else:
                response = requests.post(url, headers=headers, data=body)
        except Exception as e:
            logger.exception(f"❌ HTTP request failed: {e}")
            return None, None

        try:
            data = response.json()
        except Exception:
            logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
            data = None

        if response.status_code >= 400:
            logger.error(f"❌ Failed to fetch data. Status: {response.status_code}")
            return response.status_code, data

        return response.status_code, data

# Utility function for bot
def fetch_hmac_accounts():
    client = CoinbaseClient()
    status, accounts = client.request(method="GET", path="/v3/accounts")
    if not accounts or status != 200:
        logger.error("ERROR:nija.bot.hmac:No HMAC accounts found. Aborting bot.")
        return []
    logger.info("✅ HMAC accounts fetched successfully")
    return accounts.get("data", [])

if __name__ == "__main__":
    accounts = fetch_hmac_accounts()
    logger.info(f"Accounts: {accounts}")
