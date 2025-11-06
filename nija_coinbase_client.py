# nija_coinbase_client.py
import os
import hmac
import hashlib
import time
import base64
import json
import requests
from loguru import logger

BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

class CoinbaseClient:
    def __init__(self):
        if not all([API_KEY, API_SECRET]):
            logger.error("Coinbase API credentials not set in environment!")
            raise SystemExit(1)
        self.api_key = API_KEY
        self.api_secret = API_SECRET

    def _get_headers(self, method: str, path: str, body=""):
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

    def _request(self, method, path, body=None):
        url = BASE_URL + path
        body_str = json.dumps(body) if body else ""
        headers = self._get_headers(method, path, body_str)

        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                r = requests.post(url, headers=headers, data=body_str)
            else:
                raise ValueError("Unsupported HTTP method")
            
            if r.status_code not in [200, 201]:
                logger.error(f"Coinbase API error {r.status_code}: {r.text}")
                return {"ok": False, "error": r.text}

            return {"ok": True, "data": r.json()}
        except Exception as e:
            logger.exception("Error during Coinbase request")
            return {"ok": False, "error": str(e)}

    def get_funded_accounts(self, min_balance=10.0):
        """Return list of accounts with balance >= min_balance"""
        res = self._request("GET", "/v2/accounts")
        if not res["ok"]:
            return {"ok": False, "error": res.get("error")}

        funded = []
        for acct in res["data"]["data"]:
            balance = float(acct["balance"]["amount"])
            currency = acct["balance"]["currency"]
            if balance >= min_balance:
                funded.append({
                    "id": acct["id"],
                    "currency": currency,
                    "balance": balance
                })

        if not funded:
            return {"ok": False, "error": f"No accounts with >= {min_balance} balance"}
        return {"ok": True, "funded_accounts": funded}

    def place_order(self, account_id, side, product, size):
        """Place a market order"""
        body = {
            "type": "market",
            "side": side,
            "product_id": product,
            "funds": str(size)  # USD amount
        }
        res = self._request("POST", f"/v2/accounts/{account_id}/orders", body)
        if not res["ok"]:
            return {"ok": False, "error": res.get("error")}
        return {"ok": True, "order": res["data"]["data"]}

# Optional quick test
if __name__ == "__main__":
    client = CoinbaseClient()
    funded = client.get_funded_accounts()
    print(funded)
