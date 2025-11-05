# nija_client.py (fixed endpoint)
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
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase credentials")

        log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _generate_jwt_headers(self):
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # 5 minutes expiration
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        return headers

    def _send_request(self, endpoint):
        url = f"{self.base_url}/v2{endpoint}"  # <--- Use /v2
        headers = self._generate_jwt_headers()
        response = requests.get(url, headers=headers)

        if response.status_code == 401:
            log.error("❌ Unauthorized: JWT not accepted. Check API key permissions and JWT usage.")
            raise RuntimeError("❌ 401 Unauthorized")

        if not response.ok:
            log.error(f"❌ Request failed: {response.status_code} {response.text}")
            raise RuntimeError(f"❌ Request failed: {response.status_code}")

        return response.json()

    def get_all_accounts(self):
        """
        Returns a list of account dicts from Advanced API
        """
        data = self._send_request("/accounts")  # <--- corrected endpoint
        accounts = data.get("data", [])
        return accounts

    def get_usd_spot_balance(self):
        """
        Returns total USD balance from accounts
        """
        accounts = self.get_all_accounts()
        usd_balance = 0.0
        for acc in accounts:
            if acc.get("currency") == "USD":
                usd_balance += float(acc.get("available_balance", 0))
        return usd_balance

# Helper functions
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
