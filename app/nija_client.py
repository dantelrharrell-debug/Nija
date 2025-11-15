import os
import time
import json
import requests
import jwt  # pip install PyJWT
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, api_key=None, org_id=None, pem=None, kid=None):
        """
        Initializes CoinbaseClient.
        You can pass credentials directly OR via environment variables:
        COINBASE_API_KEY, COINBASE_ORG_ID, COINBASE_PEM_CONTENT, COINBASE_KID
        """
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self._kid = str(kid or os.getenv("COINBASE_KID"))
        self._private_key_pem = pem or os.getenv("COINBASE_PEM_CONTENT")

        if not all([self.api_key, self.org_id, self._kid, self._private_key_pem]):
            raise ValueError("CoinbaseClient missing required credentials or PEM content")

        self._private_key = self._load_private_key()
        logger.info(f"CoinbaseClient initialized with kid: {self._kid}")

    def _load_private_key(self):
        try:
            key = serialization.load_pem_private_key(
                self._private_key_pem.encode(),
                password=None,
                backend=default_backend()
            )
            return key
        except Exception as e:
            logger.error(f"Failed to load PEM key: {e}")
            raise

    def _build_jwt(self):
        now = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": now,
            "exp": now + 300
        }
        headers = {
            "kid": self._kid,
            "alg": "ES256",
            "typ": "JWT"
        }
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        logger.info(f"JWT built successfully with kid: {self._kid}, length: {len(token)}")
        return token

    def request_auto(self, method, endpoint, data=None):
        url = f"https://api.coinbase.com{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._build_jwt()}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 200:
                return response.status_code, response.json()
            else:
                content = {}
                try:
                    if response.content:
                        content = response.json()
                except json.JSONDecodeError:
                    content = {"error": response.text}
                logger.error(f"API response: {response.status_code} - {content}")
                return response.status_code, content

        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None, {}
