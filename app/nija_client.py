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
        self._kid = kid  # must be a string
        self._private_key = self._load_private_key()
        logger.info("app.nija_client:__init__: CoinbaseClient initialized.")

    def _load_private_key(self):
        try:
            return serialization.load_pem_private_key(
                self._private_key_pem.encode(),
                password=None
            )
        except Exception as e:
            logger.exception("Failed to load PEM private key")
            raise e

    def _build_jwt(self):
        """Builds a Coinbase JWT with proper ES256 PEM and kid"""
        headers = {
            "alg": "ES256",
            "kid": str(self._kid)  # Ensure kid is a string
        }

        now = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": now,
            "exp": now + 300  # 5 minutes expiration
        }

        try:
            token = jwt.encode(
                payload,
                self._private_key,
                algorithm="ES256",
                headers=headers
            )
            return token
        except Exception as e:
            logger.exception("Failed to build JWT")
            raise e

    def request_auto(self, method, url, **kwargs):
        """Send request with auto JWT auth"""
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        resp = requests.request(method, f"https://api.coinbase.com{url}", headers=headers, **kwargs)
        return resp.status_code, resp.json()
