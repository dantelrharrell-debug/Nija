# app/nija_client.py or root/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

# Setup logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase Advanced Service Key client (JWT ES256).
    Expects env:
      - COINBASE_ISS
      - COINBASE_PEM_CONTENT
      - optional: COINBASE_BASE (defaults to CDP advanced)
    """
    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv(
            "COINBASE_BASE",
            "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com/v2"
        )

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
        except Exception as e:
            logger.exception("JWT generation failed")
            raise

    def request(self, method="GET", path="/v3/accounts", json_body=None):
        url = self.base_url.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            try:
                body = r.json()
            except Exception:
                body = None
            return r.status_code, body
        except Exception as e:
            logger.exception("HTTP request failed")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Try multiple endpoints to fetch accounts. Fallback /v3 -> /v2.
        """
        paths = ["/v3/accounts", "/v2/accounts"]
        for path in paths:
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"Fetched {len(accounts)} accounts from {path}")
                return accounts
            elif status == 404:
                logger.warning(f"{path} returned 404; trying next endpoint.")
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

# Optional helper if you want
if __name__ == "__main__":
    client = CoinbaseClient(advanced=True)
    accounts = client.fetch_advanced_accounts()
    print(accounts)
