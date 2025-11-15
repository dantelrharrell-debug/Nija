import requests
import time
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, api_key, org_id, pem, kid):
        self.api_key = api_key
        self.org_id = org_id
        self._private_key_pem = pem
        self._kid = str(kid)  # ✅ must be string
        self._private_key = self._load_private_key()
        logger.info("CoinbaseClient initialized with kid: %s", self._kid)

    def _load_private_key(self):
        try:
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode(),
                password=None,
                backend=default_backend()
            )
            return private_key
        except Exception as e:
            logger.exception("Failed to load private key: %s", e)
            raise

    def _build_jwt(self):
        iat = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": iat,
            "exp": iat + 300  # 5 min expiry
        }
        headers = {"kid": self._kid}
        try:
            token = jwt.encode(
                payload,
                self._private_key,
                algorithm="ES256",
                headers=headers
            )
            logger.info("JWT built successfully with kid: %s", self._kid)
            return token
        except Exception as e:
            logger.exception("Failed to build JWT: %s", e)
            raise

    def request_auto(self, method, path, **kwargs):
        url = f"https://api.coinbase.com{path}"
        headers = {
            "Authorization": f"Bearer {self._build_jwt()}",
            "CB-VERSION": "2025-11-15",
            "Content-Type": "application/json"
        }

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            
            if not response.content:
                logger.error("API response empty")
                return response.status_code, {}

            try:
                data = response.json()
            except requests.exceptions.JSONDecodeError:
                logger.error("API returned non-JSON: %s", response.text)
                return response.status_code, {"raw_response": response.text}

            if response.status_code >= 400:
                logger.error("API error %s: %s", response.status_code, data)

            return response.status_code, data

        except requests.exceptions.RequestException as e:
            logger.exception("Request failed: %s", e)
            return None, {"error": str(e)}
