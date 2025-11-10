import time
import json
import base64
import hmac
import hashlib
from loguru import logger
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os

class CoinbaseClient:
    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT not set in environment.")
        self.base_url = "https://api.coinbase.com"
        self.session = requests.Session()
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced}")

    def _get_jwt(self):
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.exception(f"Failed to load PEM key: {e}")
            return None

        header = {"alg": "ES256", "typ": "JWT"}
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 30
        }

        # Base64 encode
        def b64encode(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=")

        signing_input = b64encode(header) + b"." + b64encode(payload)

        try:
            signature = private_key.sign(
                signing_input,
                ec.ECDSA(hashlib.sha256())
            )
            jwt_token = signing_input.decode() + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")
            return jwt_token
        except Exception as e:
            logger.exception(f"Failed to sign JWT: {e}")
            return None

    def request(self, method="GET", path="", params=None):
        url = self.base_url + path
        headers = {}
        if self.advanced:
            jwt_token = self._get_jwt()
            if not jwt_token:
                return None, None
            headers["Authorization"] = f"Bearer {jwt_token}"

        try:
            resp = self.session.request(method, url, headers=headers, params=params, timeout=10)
            try:
                data = resp.json()
            except json.JSONDecodeError:
                logger.warning(f"⚠️ JSON decode failed. Status: {resp.status_code}, Body: {resp.text}")
                return resp.status_code, None
            return resp.status_code, data
        except requests.RequestException as e:
            logger.exception(f"HTTP request failed: {e}")
            return None, None

    def fetch_advanced_accounts(self):
        status, data = self.request("GET", "/v3/accounts")
        if status != 200 or not data:
            logger.error(f"❌ Failed to fetch accounts. Status: {status}")
            return []
        accounts = data.get("data", [])
        logger.info(f"✅ Fetched {len(accounts)} accounts.")
        return accounts
