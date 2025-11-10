# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

class CoinbaseClient:
    def __init__(self, advanced=True):
        """
        Initialize the CoinbaseClient.
        advanced=True uses Service Key (Advanced) API.
        """
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")

        # Generate JWT token for authentication
        self.token = self._generate_jwt()
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced}")

    def _generate_jwt(self):
        """
        Generate a JWT token from the Service Key PEM and ISS.
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
                "exp": int(time.time()) + 300  # token valid for 5 minutes
            }
            token = jwt.encode(payload, private_key, algorithm="ES256")
            return token
        except Exception as e:
            logger.exception(f"JWT generation failed: {e}")
            raise

    def request(self, method="GET", path="/accounts"):
        """
        Make a request to the Coinbase Advanced API.
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
        Fetch accounts from the Coinbase Advanced API.
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
