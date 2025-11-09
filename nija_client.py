# nija_client.py

import os
import time
import json
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, passphrase=None, base=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        logger.info("CoinbaseClient initialized")
        logger.info("Advanced mode: Yes")

    def _sign(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        hmac_key = self.api_secret.encode()  # Use raw secret, NOT base64
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()
        return timestamp, signature_b64

    def fetch_accounts(self):
        url = f"{self.base}/v2/accounts"
        try:
            ts, sig = self._sign("GET", "/v2/accounts")
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": sig,
                "CB-ACCESS-TIMESTAMP": ts,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
            }
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching accounts: {e}")
            return []

# === Backwards-compatibility aliases ===
def _alias_if_missing():
    try:
        if not hasattr(CoinbaseClient, "get_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.get_accounts = CoinbaseClient.fetch_accounts

        if not hasattr(CoinbaseClient, "get_balances"):
            if hasattr(CoinbaseClient, "get_account_balances"):
                CoinbaseClient.get_balances = CoinbaseClient.get_account_balances
            elif hasattr(CoinbaseClient, "get_accounts"):
                def _get_balances(self):
                    return self.get_accounts()
                CoinbaseClient.get_balances = _get_balances

        if not hasattr(CoinbaseClient, "list_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.list_accounts = CoinbaseClient.fetch_accounts
    except Exception:
        pass

_alias_if_missing()
