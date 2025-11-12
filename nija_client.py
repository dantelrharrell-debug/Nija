import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        self.base = os.environ.get("COINBASE_ADVANCED_BASE")
        self.issuer = os.environ.get("COINBASE_JWT_ISSUER")
        self.audience = os.environ.get("COINBASE_JWT_AUDIENCE")
        self._load_and_validate_pem()
        logger.info("CoinbaseClient initialized. base=%s", self.base)

    def _load_and_validate_pem(self):
        pem_content = os.environ.get("COINBASE_JWT_PEM")
        if not pem_content:
            raise ValueError("COINBASE_JWT_PEM not provided")
        self.private_key = serialization.load_pem_private_key(
            pem_content.encode(), password=None, backend=default_backend()
        )
        logger.debug("PEM validation succeeded.")

    def _get_jwt(self):
        payload = {
            "iss": self.issuer,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,  # 5 min
            "aud": self.audience
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    def _request(self, method, endpoint, max_retries=3):
        url = f"{self.base}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._get_jwt()}",
            "Content-Type": "application/json"
        }
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.request(method, url, headers=headers)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError as e:
                logger.warning("HTTP request failed (attempt %d/%d) for %s: %s",
                               attempt, max_retries, url, e)
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)  # exponential backoff

    # --- Public Methods ---
    def get_accounts(self):
        return self._request("GET", "/accounts")

    def place_order(self, order_payload):
        return self._request("POST", "/orders", order_payload)
