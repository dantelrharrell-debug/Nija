# nija_client.py
import jwt
import time
from loguru import logger
from cryptography.hazmat.primitives import serialization
import requests

class CoinbaseClient:
    def __init__(self, api_key, org_id, pem, kid):
        self.api_key = api_key
        self.org_id = org_id
        self._private_key_pem = pem
        self._kid = str(kid)  # ✅ must be a string
        self._private_key = self._load_private_key()
        logger.info(f"CoinbaseClient initialized with kid: {self._kid}")

    def _load_private_key(self):
        try:
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode(),
                password=None
            )
            return private_key
        except Exception as e:
            logger.exception("Failed to load PEM private key")
            raise e

    def _build_jwt(self):
        """Builds a Coinbase JWT with proper ES256 PEM and kid"""
        headers = {
            "alg": "ES256",
            "kid": self._kid  # ✅ header.kid must not be None
        }
        now = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": now,
            "exp": now + 300  # 5 min expiration
        }

        try:
            token = jwt.encode(
                payload,
                self._private_key,
                algorithm="ES256",
                headers=headers
            )
            logger.info(f"JWT built successfully with kid: {self._kid}")
            return token
        except Exception as e:
            logger.exception("Failed to build JWT")
            raise e

    def request_auto(self, method, url, **kwargs):
        """Wrapper for Coinbase API requests with JWT auth"""
        try:
            token = self._build_jwt()
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {token}"
            response = requests.request(method, f"https://api.coinbase.com{url}", headers=headers, **kwargs)

            if response.status_code != 200:
                logger.error(f"API response: {response.status_code} - {response.text}")
                return response.status_code, response.json() if response.content else {}
            return response.status_code, response.json()
        except Exception as e:
            logger.exception("Request failed")
            return None, {}
