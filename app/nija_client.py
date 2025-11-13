# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # --- Load environment variables ---
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT")
        self.api_key = os.environ.get("COINBASE_API_KEY")

        if not all([self.org_id, self.pem_raw, self.api_key]):
            raise ValueError("Missing Coinbase credentials in environment variables")

        # --- Load PEM key safely ---
        try:
            self.pem = serialization.load_pem_private_key(
                self.pem_raw.encode("utf-8"),
                password=None,
                backend=default_backend()
            )
            logger.info("PEM key loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load PEM key: {e}")
            raise

        # Coinbase REST base URL
        self.base_url = "https://api.coinbase.com"

    def _generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,  # JWT valid 5 minutes
            "sub": self.api_key,
            "org_id": self.org_id
        }
        try:
            token = jwt.encode(
                payload,
                self.pem,
                algorithm="ES256",
            )
            return token
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _headers(self):
        token = self._generate_jwt()
        return {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-13",
            "Content-Type": "application/json"
        }

    # Example: validate API access
    def validate_coinbase(self):
        url = f"{self.base_url}/v2/accounts"
        try:
            response = requests.get(url, headers=self._headers())
            if response.status_code == 200:
                logger.success("Coinbase credentials validated successfully")
                return response.json()
            else:
                logger.error(f"Coinbase API returned {response.status_code}: {response.text}")
                raise RuntimeError(f"Unauthorized: {response.status_code}")
        except Exception as e:
            logger.error(f"Error during Coinbase validation: {e}")
            raise

    # Example method to get accounts
    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        response = requests.get(url, headers=self._headers())
        if response.status_code != 200:
            logger.error(f"Failed to fetch accounts: {response.status_code} {response.text}")
            raise RuntimeError("Failed to fetch accounts")
        return response.json()
