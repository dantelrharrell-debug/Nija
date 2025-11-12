# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # Load environment variables
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.base = f"https://api.coinbase.com/v2/organizations/{self.org_id}"
        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")
        self.pem = os.getenv("COINBASE_JWT_PEM").encode()
        self._load_and_validate_pem()
        logger.info(f"Advanced JWT auth enabled (PEM validated). kid={self.kid}, issuer={self.issuer}")

    def _load_and_validate_pem(self):
        try:
            self.private_key = serialization.load_pem_private_key(
                self.pem,
                password=None,
                backend=default_backend()
            )
            logger.debug("PEM validation via cryptography succeeded.")
        except Exception as e:
            logger.error(f"PEM validation failed: {e}")
            raise

    def _generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 30,
            "iss": self.issuer
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.kid})
        return token

    def _request(self, method, endpoint, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._generate_jwt()}"
        headers["CB-VERSION"] = "2025-11-12"
        url = self.base + endpoint

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            raise

    # === Public API ===
    def get_accounts(self):
        """
        Fetch all accounts for the organization
        """
        return self._request("GET", "/accounts")

    def create_order(self, account_id, amount, currency, side="buy"):
        """
        Create a new order on a specific account
        """
        data = {
            "amount": amount,
            "currency": currency,
            "side": side
        }
        return self._request("POST", f"/accounts/{account_id}/orders", json=data)

    def get_account(self, account_id):
        """
        Fetch a single account
        """
        return self._request("GET", f"/accounts/{account_id}")
