# nija_client.py
import jwt
import time
import logging
from loguru import logger
from cryptography.hazmat.primitives import serialization
from requests import request

class CoinbaseClient:
    def __init__(self, api_key, org_id, pem, kid):
        self.api_key = api_key
        self.org_id = org_id
        self._private_key_pem = pem
        self._kid = str(kid)  # ✅ must be a string
        self._private_key = self._load_private_key()
        logger.info("CoinbaseClient initialized with kid: %s", self._kid)

    def _load_private_key(self):
        """Load PEM private key for JWT signing"""
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
        """Builds a Coinbase JWT with ES256 PEM and kid"""
        headers = {
            "alg": "ES256",
            "kid": self._kid
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
            logger.info("JWT built successfully")
            return token
        except Exception as e:
            logger.exception("Failed to build JWT")
            raise e

    def request_auto(self, method, url, **kwargs):
        """Send request to Coinbase API with auto JWT authorization"""
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        try:
            resp = request(method, f"https://api.coinbase.com{url}", headers=headers, **kwargs)
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, resp.text
        except Exception as e:
            logger.exception("Failed to make request to Coinbase")
            raise e

# Optional: Test JWT without calling API
if __name__ == "__main__":
    api_key = "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
    kid = "9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
    org_id = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
    pem = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIKrWQ2OeX7kqTob0aXR6A238b698ePPLutcEP1qq4gfLoAoGCCqGSM49
AwEHoUQDQgAEuQAqrVE522Hz...
-----END EC PRIVATE KEY-----"""

    client = CoinbaseClient(api_key, org_id, pem, kid)
    token = client._build_jwt()
    print("JWT:", token)
    header = jwt.get_unverified_header(token)
    print("JWT header:", header)
