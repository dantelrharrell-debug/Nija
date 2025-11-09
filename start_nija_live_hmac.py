import os
import time
import hmac
import hashlib
import requests
import asyncio
from loguru import logger

# ---------- HMAC v3 Coinbase Client ----------
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

# ---------- Fetch accounts safely ----------
def fetch_hmac_accounts():
    client = CoinbaseClient()
    status, accounts = client.request("GET", "/v3/accounts")  # <-- v3 endpoint
    if status != 200 or not accounts:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []
    return accounts

# ---------- Main bot loop ----------
async def main_loop():
    logger.info("Starting HMAC live bot...")
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("No HMAC accounts found. Aborting bot.")
        return

    logger.info(f"Accounts fetched: {accounts}")

    # Example live loop (replace with your trading logic)
    while True:
        for account in accounts:
            logger.info(f"Checking account: {account.get('id')}")
        await asyncio.sleep(10)  # Loop delay

if __name__ == "__main__":
    asyncio.run(main_loop())
