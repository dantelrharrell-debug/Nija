# nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

class CoinbaseClient:
    """
    Coinbase Advanced Client (JWT Service Key)
    """
    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")
        self.token = self._generate_jwt()
        self.base_url = "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com/v2"
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced}")

    def _generate_jwt(self):
        """
        Generates JWT token for Coinbase Advanced API
        """
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
            payload = {
                "iss": self.iss,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300
            }
            token = jwt.encode(payload, private_key, algorithm="ES256")
            return token
        except Exception as e:
            logger.exception(f"JWT generation failed: {e}")
            raise

    def request(self, method="GET", path="/accounts"):
        """
        Make a request to Coinbase Advanced API
        """
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.request(method, url, headers=headers)
            try:
                data = response.json()
            except Exception:
                data = None
            return response.status_code, data
        except Exception as e:
            logger.exception(f"Request failed: {e}")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Fetch all accounts from Coinbase Advanced API
        """
        try:
            status, data = self.request("/accounts")
            if status != 200 or not data:
                logger.error(f"❌ Failed to fetch accounts. Status: {status}")
                return []
            accounts = data.get("data", [])
            logger.info(f"✅ Fetched {len(accounts)} accounts.")
            return accounts
        except Exception as e:
            logger.exception(f"Failed to fetch accounts: {e}")
            return []
