import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # Load environment variables
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT")

        if not all([self.org_id, self.api_key, self.pem_raw]):
            raise ValueError("Missing Coinbase environment variables!")

        # Fix PEM formatting
        self.pem = self.pem_raw.replace("\\n", "\n")

        # Load key
        try:
            self.private_key = serialization.load_pem_private_key(
                self.pem.encode(),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.error(f"Failed to load PEM key: {e}")
            raise

        logger.info("CoinbaseClient initialized successfully.")

    def _generate_jwt(self):
        payload = {
            "sub": self.api_key,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,  # 5 min expiry
            "kid": self.api_key
        }

        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    def validate_coinbase(self):
        jwt_token = self._generate_jwt()
        headers = {
            "CB-VERSION": "2025-01-01",
            "Authorization": f"Bearer {jwt_token}"
        }
        url = f"https://api.coinbase.com/v2/accounts"
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                logger.success("Coinbase authentication successful!")
            else:
                logger.error(f"Coinbase auth failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Request error: {e}")
