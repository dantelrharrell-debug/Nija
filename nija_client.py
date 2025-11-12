# nija_client.py

import os
import json
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization

class CoinbaseClient:
    def __init__(self):
        self.org_id = os.getenv("COINBASE_ORG_ID")
        if not self.org_id:
            raise ValueError("COINBASE_ORG_ID not set in environment")

        self.base = f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}"
        self._load_and_validate_pem()
        logger.info(f"CoinbaseClient initialized with org_id={self.org_id}")

    def _load_and_validate_pem(self):
        pem_content = os.getenv("COINBASE_JWT_PEM")
        if not pem_content:
            raise ValueError("COINBASE_JWT_PEM not found in environment")

        try:
            # Load PEM
            self._private_key = serialization.load_pem_private_key(
                pem_content.encode("utf-8"),
                password=None
            )
            logger.debug("PEM validation via cryptography succeeded")
        except Exception as e:
            logger.error(f"Failed to load PEM: {e}")
            raise

        # JWT claims
        self.kid = os.getenv("COINBASE_KEY_ID")
        self.issuer = os.getenv("COINBASE_ISSUER")
        if not self.kid or not self.issuer:
            raise ValueError("COINBASE_KEY_ID or COINBASE_ISSUER not set")

    def _jwt_headers(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,
            "iss": self.issuer,
        }
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers={"kid": self.kid})
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request(self, method, path, data=None, params=None):
        url = f"{self.base}{path}"
        headers = self._jwt_headers()
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                r = requests.post(url, headers=headers, json=data)
            else:
                raise ValueError("Unsupported HTTP method")
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Request exception for {url}: {e}")
            raise

    # --- Example methods ---

    def get_accounts(self):
        """
        Returns all accounts for the organization.
        Endpoint: GET /accounts
        """
        return self._request("GET", "/accounts")

    def get_positions(self):
        """
        Returns all positions for the org.
        Endpoint: GET /positions
        """
        return self._request("GET", "/positions")

    def place_order(self, account_id, side, product_id, size, order_type="market"):
        """
        Place a new order.
        Endpoint: POST /orders
        """
        data = {
            "account_id": account_id,
            "side": side,       # "buy" or "sell"
            "product_id": product_id,  # e.g., "BTC-USD"
            "size": size,       # string or float
            "type": order_type
        }
        return self._request("POST", "/orders", data=data)

    def get_order(self, order_id):
        """
        Fetch a specific order by ID.
        Endpoint: GET /orders/:id
        """
        return self._request("GET", f"/orders/{order_id}")
