# nija_client.py
import jwt
import time
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import requests

class CoinbaseClient:
    def __init__(self, api_key, org_id, pem, kid):
        self.api_key = api_key
        self.org_id = org_id
        self._private_key_pem = pem
        self._kid = str(kid)  # ✅ ensure string
        self._private_key = self._load_private_key()
        logger.info("CoinbaseClient initialized with kid: %s", self._kid)

    def _load_private_key(self):
        try:
            return serialization.load_pem_private_key(
                self._private_key_pem.encode("utf-8"),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.exception("Failed to load PEM private key")
            raise e

    def _build_jwt(self):
        now = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": now,
            "exp": now + 300  # 5 min
        }
        headers = {"alg": "ES256", "kid": self._kid}  # ✅ fixed
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        logger.info("JWT built successfully with kid: %s", self._kid)
        return token

    def request_auto(self, method, url, **kwargs):
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["CB-VERSION"] = "2025-11-15"
        try:
            resp = requests.request(method, f"https://api.coinbase.com{url}", headers=headers, **kwargs)
            if resp.status_code != 200:
                logger.error("API response: %s", resp.text)
            return resp.status_code, resp.json() if resp.content and resp.headers.get('Content-Type','').startswith('application/json') else {}
        except Exception as e:
            logger.exception("Request failed")
            return None, None
