import os
import time
import jwt
import requests
import logging

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Passphrase is optional for Advanced JWT keys
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
        self.base_url = "https://api.coinbase.com"

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API key or secret")

        if not self.passphrase:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _generate_jwt(self, endpoint="/v2/accounts", method="GET", body=""):
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # token valid for 5 minutes
            "sub": self.api_key,
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def _send_request(self, endpoint, method="GET", body=None):
        url = f"{self.base_url}{endpoint}"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self._generate_jwt(endpoint, method, body or ""),
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        try:
            response = requests.request(method, url, headers=headers, json=body)
            if response.status_code == 401:
                log.error(f"❌ Unauthorized: Check API key permissions and JWT usage. Response: {response.text}")
                raise RuntimeError("❌ 401 Unauthorized")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"❌ Request failed: {e}")
            raise

    def get_all_accounts(self):
        data = self._send_request("/v2/accounts")
        return data.get("data", [])

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for acct in accounts:
            if acct.get("currency") == "USD":
                return float(acct.get("balance", {}).get("amount", 0))
        return 0.0

# ===== Helpers for direct import (keeps nija_debug.py working) =====
def get_all_accounts():
    client = CoinbaseClient()
    return client.get_all_accounts()

def get_usd_spot_balance():
    client = CoinbaseClient()
    return client.get_usd_spot_balance()

# Optional test when running this file directly
if __name__ == "__main__":
    client = CoinbaseClient()
    print("USD Spot Balance:", client.get_usd_spot_balance())
