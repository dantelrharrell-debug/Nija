import os
import hmac
import hashlib
import base64
import time
import json
import requests

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Coinbase API credentials missing in environment variables.")

    def _generate_jwt(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(signature).decode()

    def get_all_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET','/v2/accounts')}",
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers)
        if response.ok:
            return response.json().get("data", [])
        else:
            raise RuntimeError(f"❌ Failed to fetch accounts: {response.status_code} {response.text}")

    def get_funded_account(self):
        accounts = self.get_all_accounts()
        for acc in accounts:
            balance = float(acc.get("balance", {}).get("amount", 0))
            if balance > 0:
                return acc
        return None
