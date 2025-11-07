#!/usr/bin/env python3
"""
nija_client.py
Clean Coinbase Advanced Trade API client for Nija bot.
Supports: get_accounts(), get_account_by_currency(), submit_order()
No passphrase required.
"""

import os
import requests
import json
from typing import List, Optional

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret must be set in environment variables")

        self.headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2025-01-01",  # use a fixed version
            "Content-Type": "application/json"
        }
        print("CoinbaseClient initialized successfully ✅")

    def _request(self, method: str, path: str, data: Optional[dict] = None):
        url = f"{self.base_url}{path}"
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=self.headers, timeout=10)
            elif method.upper() == "POST":
                r = requests.post(url, headers=self.headers, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP error: {e}")
            if e.response is not None:
                print(f"Status code: {e.response.status_code}, Response: {e.response.text}")
            raise
        except Exception as e:
            print(f"Request error: {e}")
            raise

    def get_accounts(self) -> List[dict]:
        """Return all accounts (wallets/portfolio)"""
        data = self._request("GET", "/platform/v2/accounts")
        return data.get("data", [])

    def get_account_by_currency(self, currency: str) -> Optional[dict]:
        """Return a single account by currency symbol (USD, BTC, ETH, etc.)"""
        accounts = self.get_accounts()
        for acct in accounts:
            if acct.get("balance", {}).get("currency") == currency.upper():
                return acct
        return None

    def submit_order(self, account_id: str, side: str, product_id: str, size: str, order_type="market"):
        """
        Submit a trade order
        side: 'buy' or 'sell'
        product_id: e.g., 'BTC-USD'
        size: amount in base currency
        order_type: 'market' or 'limit'
        """
        data = {
            "account_id": account_id,
            "side": side.lower(),
            "product_id": product_id.upper(),
            "size": size,
            "type": order_type
        }
        return self._request("POST", "/platform/v2/orders", data=data)


if __name__ == "__main__":
    # Quick test to check connection & balance
    c = CoinbaseClient()
    try:
        accounts = c.get_accounts()
        if not accounts:
            print("No accounts returned. Check API key permissions or IP allowlist ❌")
        else:
            print("Connected accounts:")
            for a in accounts:
                name = a.get("name", "<unknown>")
                bal = a.get("balance", {})
                print(f"{name}: {bal.get('amount','0')} {bal.get('currency','?')}")
    except Exception as e:
        print("Error connecting to Coinbase:", e)
