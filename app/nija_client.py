import time
import json
import requests
import jwt  # pip install PyJWT
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os


class CoinbaseClient:
    def __init__(self, api_key, org_id, pem, kid):
        self.api_key = str(api_key)
        self.org_id = str(org_id)
        self._kid = str(kid)
        self._private_key_pem = pem
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
        """Build JWT for Coinbase Advanced API auth."""
        try:
            now = int(time.time())
            payload = {
                "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
                "iat": now,
                "exp": now + 300  # 5 minutes expiry
            }
            headers = {
                "kid": self._kid,
                "alg": "ES256",
                "typ": "JWT"
            }
            token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
            logger.info(f"JWT built successfully with kid: {self._kid}, length: {len(token)}")
            return token
        except Exception as e:
            logger.error(f"Failed to build JWT: {e}")
            raise

    def request_auto(self, method, endpoint, data=None):
        """Make Coinbase API requests with JWT auth."""
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
                # Handle empty or unauthorized responses safely
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
