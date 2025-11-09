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
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
        self.api_base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # Retail default
        self.org_id = os.getenv("COINBASE_ORG_ID", None)  # Advanced API
        self.is_advanced = bool(self.org_id)
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.is_advanced}")

    def _sign_request(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        key_bytes = self.api_secret.encode("utf-8")
        signature = hmac.new(key_bytes, message.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
        }
        if self.is_advanced and self.org_id:
            headers["CB-ACCESS-ORG"] = self.org_id
        if body:
            headers["Content-Type"] = "application/json"
        return headers

    def request(self, method="GET", path="/v3/accounts", body=""):
        url = self.api_base + path
        headers = self._sign_request(method, path, body)
        try:
            response = requests.request(method, url, headers=headers, data=body, timeout=10)
        except requests.RequestException as e:
            logger.error(f"Network error: {e}")
            return None, []

        try:
            data = response.json()
        except Exception:
            logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
            data = None

        return response.status_code, data

def fetch_hmac_accounts():
    client = CoinbaseClient()

    endpoints = ["/v3/accounts", "/v2/accounts"]  # Try v3 first, then fallback v2
    for path in endpoints:
        status, accounts = client.request("GET", path)
        if status == 200 and accounts:
            logger.info(f"✅ Fetched {len(accounts)} accounts from {path}")
            return accounts
        elif status == 401:
            logger.error(f"❌ Unauthorized. Check your API key/secret and permissions for {path}")
            return []
        elif status == 404:
            logger.warning(f"⚠️ {path} not found (404). Trying next endpoint...")
        else:
            logger.warning(f"⚠️ Failed to fetch accounts. Status: {status}. Body: {accounts}")

    logger.error("❌ No HMAC accounts found after checking all endpoints.")
    return []

if __name__ == "__main__":
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("No accounts returned. Bot will not start.")
    else:
        logger.info(f"Accounts ready: {accounts}")
