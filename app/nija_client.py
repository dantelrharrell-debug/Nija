# nija_client.py
import os
import time
import jwt
import requests
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = "https://api.coinbase.com"

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API credentials")

        log.info("⚠️ No passphrase required for Advanced JWT keys.")
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_jwt_token(self):
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # 5 min expiration
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def _send_request(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}{endpoint}"
        token = self._get_jwt_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers)
            else:
                resp = requests.post(url, headers=headers, json=data)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                log.error("❌ Unauthorized: JWT not accepted. Check key permissions.")
                raise RuntimeError("❌ 401 Unauthorized")
            else:
                log.error(f"❌ Request failed: {resp.status_code} {resp.text}")
                raise RuntimeError(f"❌ Request failed: {resp.status_code}")
        except Exception as e:
            log.error(f"❌ Request exception: {e}")
            raise

    def get_all_accounts(self):
        return self._send_request("/v2/accounts")

    def get_usd_spot_balance(self):
        accounts_data = self.get_all_accounts()
        usd_balance = 0.0
        for account in accounts_data.get("data", []):
            if account.get("currency") == "USD":
                usd_balance = float(account.get("balance", {}).get("amount", 0))
        return usd_balance


# Helper functions for nija_debug.py
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
