#!/usr/bin/env python3
import os
import time
import hmac
import hashlib
import base64
import requests
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.hmac")

# Environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")  # Retail HMAC base
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # Optional for Retail HMAC

# HMAC Client
class CoinbaseHMACClient:
    def __init__(self, key, secret, base=API_BASE):
        self.key = key
        self.secret = secret.encode()
        self.base = base.rstrip("/")

    def _sign(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(self.secret, message.encode(), hashlib.sha256).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        return headers

    def request(self, method, path, body=""):
        url = self.base + path
        headers = self._sign(method, path, body)
        try:
            response = requests.request(method, url, headers=headers, data=body, timeout=10)
        except Exception as e:
            logger.error(f"⚠️ Request failed: {e}")
            return None, None

        try:
            return response.status_code, response.json()
        except Exception:
            logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
            return response.status_code, None

# Fetch accounts safely
def fetch_hmac_accounts():
    client = CoinbaseHMACClient(API_KEY, API_SECRET)
    status, accounts = client.request("GET", "/accounts")  # Correct Retail HMAC endpoint
    if status != 200 or accounts is None:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return []
    return accounts

# Main async loop
async def main_loop():
    while True:
        accounts = fetch_hmac_accounts()
        if not accounts:
            logger.warning("No HMAC accounts found. Waiting 30s before retry...")
            await asyncio.sleep(30)
            continue

        # Example: log balances for each account
        for acct in accounts:
            balance = acct.get("balance", {})
            logger.info(f"Account {acct.get('id')} ({acct.get('currency')}): {balance.get('amount')}")

        # Replace this with your trading logic
        await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
