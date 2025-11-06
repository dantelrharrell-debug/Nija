# nija_client.py
import os
import hmac
import hashlib
import time
import requests
import json
from typing import List

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")  # Advanced API base

        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key/secret not set!")

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def list_accounts(self) -> List[dict]:
        path = "/platform/v2/accounts"
        url = self.base_url + path
        try:
            resp = requests.get(url, headers=self._headers("GET", path))
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except Exception as e:
            print("Error fetching accounts:", e)
            return []

# ✅ Position size helper
def calculate_position_size(account_balance, risk_per_trade, entry_price, stop_loss):
    """
    Calculate position size based on account balance, risk %, entry price, and stop loss.
    """
    risk_amount = account_balance * risk_per_trade
    position_size = risk_amount / abs(entry_price - stop_loss)
    return position_size
