# nija_client.py (root) - JWT / Advanced Service Key client (root-only)
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase Advanced Service Key client (JWT ES256).
    Requires COINBASE_ISS and COINBASE_PEM_CONTENT in env.
    """
    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com/v2")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")

        self.token = self._generate_jwt()
        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url}")

    def _generate_jwt(self):
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
            payload = {"iss": self.iss, "iat": int(time.time()), "exp": int(time.time()) + 300}
            token = jwt.encode(payload, private_key, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode()
            return token
        except Exception:
            logger.exception("JWT generation failed")
            raise

    def request(self, method="GET", path="/v3/accounts", json_body=None):
        url = self.base_url.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            try:
                body = r.json()
            except Exception:
                body = r.text
            return r.status_code, body
        except Exception:
            logger.exception("HTTP request failed")
            return None, None

    def fetch_advanced_accounts(self):
        status, body = self.request("GET", "/v3/accounts")
        if status == 404:
            logger.warning("/v3/accounts returned 404; endpoint not available.")
            return []
        if status != 200 or not body:
            logger.error(f"Failed to fetch accounts. status={status} body={body}")
            return []
        accounts = body.get("data", []) if isinstance(body, dict) else []
        logger.info(f"Fetched {len(accounts)} account(s).")
        return accounts
