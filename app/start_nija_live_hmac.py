# start_nija_live_hmac_safe.py
import os
import hmac
import hashlib
import time
import requests
from loguru import logger

# -----------------------------
# HMAC Coinbase Client
# -----------------------------
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        if not self.api_key or not self.api_secret:
            logger.error("Missing Coinbase API key or secret.")
            raise ValueError("Missing Coinbase API key or secret")

    def _sign(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        return headers

    def request(self, method="GET", path="/accounts", body=""):
        url = self.base + path
        headers = self._sign(method, path, body)
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            else:
                response = requests.post(url, headers=headers, data=body)
            try:
                data = response.json()
            except Exception:
                logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
                data = {}
            return response.status_code, data
        except Exception as e:
            logger.exception(f"❌ Request failed: {e}")
            return None, {}

# -----------------------------
# Fetch HMAC Accounts safely
# -----------------------------
def fetch_hmac_accounts():
    client = CoinbaseClient()
    status, accounts = client.request(method="GET", path="/accounts")

    if status == 200 and accounts:
        logger.info("✅ Accounts fetched:")
        for acct in accounts.get("data", []):
            name = acct.get("name")
            currency = acct.get("currency")
            balance = acct.get("balance", {}).get("amount")
            logger.info(f"{name} ({currency}): {balance}")
        return accounts.get("data", [])
    else:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []

# -----------------------------
# Main Loop (async ready)
# -----------------------------
import asyncio

async def main_loop():
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.warning("No HMAC accounts found. Bot will not proceed.")
        return
    # You can continue your trading bot logic here
    logger.info("✅ HMAC accounts ready, continue bot logic...")

if __name__ == "__main__":
    asyncio.run(main_loop())
