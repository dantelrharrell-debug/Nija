# nija_coinbase_client.py
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
        self.base_url = "https://api.cdp.coinbase.com"
        if not self.api_key or not self.api_secret:
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment variables.")

    def _get_headers(self, method: str, path: str, body: str = ""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/platform/v2/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)
        response = requests.get(url, headers=headers, timeout=10)
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Error decoding Coinbase response: {e}")
            return {"ok": False, "error": str(e)}
        if response.status_code != 200:
            logger.error(f"Coinbase API error {response.status_code}: {data}")
            return {"ok": False, "error": data}
        return {"ok": True, "accounts": data}

    def get_funded_accounts(self, min_balance=0.01):
        result = self.get_accounts()
        if not result["ok"]:
            return result
        accounts = result["accounts"].get("data", [])
        funded = [
            {
                "id": acct["id"],
                "currency": acct["currency"],
                "balance": float(acct["balance"]["amount"])
            }
            for acct in accounts
            if float(acct["balance"]["amount"]) >= min_balance
        ]
        return {"ok": True, "funded_accounts": funded}

    def place_order(self, account_id: str, side: str, product_id: str, size: float, price: float = None):
        """
        side: 'buy' or 'sell'
        size: amount of base currency
        price: required for limit orders (optional for market)
        """
        path = "/orders"
        url = self.base_url + path
        body_dict = {
            "account_id": account_id,
            "side": side,
            "product_id": product_id,
            "size": str(size)
        }
        if price is not None:
            body_dict["price"] = str(price)
            body_dict["type"] = "limit"
        else:
            body_dict["type"] = "market"
        import json
        body_json = json.dumps(body_dict)
        headers = self._get_headers("POST", path, body_json)
        response = requests.post(url, headers=headers, data=body_json, timeout=10)
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Error decoding Coinbase response: {e}")
            return {"ok": False, "error": str(e)}
        if response.status_code != 200:
            logger.error(f"Coinbase API error {response.status_code}: {data}")
            return {"ok": False, "error": data}
        return {"ok": True, "order": data}

# Quick test
if __name__ == "__main__":
    client = CoinbaseClient()
    funded = client.get_funded_accounts()
    if funded["ok"]:
        logger.info(f"Funded accounts: {funded['funded_accounts']}")
    else:
        logger.error(f"Error fetching funded accounts: {funded}")
