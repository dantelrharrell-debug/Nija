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
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API key or secret")

        log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _generate_jwt(self, request_path, method="GET", body=""):
        """Generate JWT for Advanced key"""
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 300,  # valid 5 min
            "sub": self.api_key,
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def _send_request(self, endpoint, method="GET", body=None):
        url = f"{self.base_url}{endpoint}"
        jwt_token = self._generate_jwt(endpoint, method, body or "")

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.request(method, url, headers=headers, json=body)
            if response.status_code == 401:
                log.error(f"❌ Unauthorized: JWT not accepted. Response: {response.text}")
                raise RuntimeError("❌ 401 Unauthorized")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"❌ Request failed: {e}")
            raise

    def get_all_accounts(self):
        """Return all accounts"""
        data = self._send_request("/v2/accounts")
        return data.get("data", [])

    def get_usd_spot_balance(self):
        """Return USD spot balance"""
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return float(acc.get("balance", {}).get("amount", 0))
        return 0.0


# Helper functions to keep nija_debug.py compatible
client = CoinbaseClient()


def get_all_accounts():
    return client.get_all_accounts()


def get_usd_spot_balance():
    return client.get_usd_spot_balance()
