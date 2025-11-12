# nija_client.py
import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # Load environment settings
        self.org_id = os.getenv("COINBASE_ORG_ID")
        if not self.org_id:
            raise ValueError("COINBASE_ORG_ID env var missing")

        # Use Advanced Trade API brokerage base from docs
        self.base = os.getenv("COINBASE_ADVANCED_BASE",
                              f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}")
        logger.info(f"Using Coinbase Advanced API base URL: {self.base}")

        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")
        self.pem = os.getenv("COINBASE_JWT_PEM")
        if not self.pem:
            raise ValueError("COINBASE_JWT_PEM env var missing")
        self._load_and_validate_pem()

        logger.info(f"Advanced JWT auth enabled (kid={self.kid}, issuer={self.issuer})")

    def _load_and_validate_pem(self):
        try:
            self.private_key = serialization.load_pem_private_key(
                self.pem.encode(), password=None, backend=default_backend()
            )
            logger.debug("PEM validation via cryptography succeeded.")
        except Exception as e:
            logger.error(f"PEM validation failed: {e}")
            raise

    def _generate_jwt(self):
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "iat": now,
            "exp": now + 300,  # expires in 5 min
        }
        headers = {"kid": self.kid}
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode("utf‑8")
        return token

    def _request(self, method, endpoint, params=None, data=None, max_retries=3):
        url = f"{self.base}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "Content-Type": "application/json"
        }
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.request(method, url, headers=headers, params=params, json=data, timeout=15)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP request failed (attempt {attempt}/{max_retries}) for {url}: {e}")
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Request error for {url}: {e}")
                raise

    # === Endpoint Methods ===

    def list_accounts(self):
        """GET /accounts — list all accounts for organization"""
        return self._request("GET", "/accounts")

    def get_account(self, account_id):
        """GET /accounts/{account_id} — get specific account"""
        return self._request("GET", f"/accounts/{account_id}")

    def list_orders(self, params=None):
        """GET /orders/historical/batch — list past orders"""
        return self._request("GET", "/orders/historical/batch", params=params)

    def get_order(self, order_id):
        """GET /orders/historical/{order_id} — fetch order by ID"""
        return self._request("GET", f"/orders/historical/{order_id}")

    def create_order(self, order_body):
        """POST /orders — place a new order"""
        return self._request("POST", "/orders", data=order_body)

    def cancel_orders(self, cancel_body):
        """POST /orders/batch_cancel — cancel orders batch"""
        return self._request("POST", "/orders/batch_cancel", data=cancel_body)

    # Add more endpoints here as required (fills, products, convert, etc.)

if __name__ == "__main__":
    # Quick test run (requires environment configured)
    client = CoinbaseClient()
    try:
        accounts = client.list_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
