# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        # Advanced Trade API base
        self.base_url = "https://api.exchange.coinbase.com"

        # JWT Auth
        self.pkey = os.getenv("COINBASE_JWT_PEM")
        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")

        if not self.pkey or not self.kid or not self.issuer:
            raise ValueError("Missing Coinbase JWT credentials")

        logger.info("Advanced JWT auth enabled (PEM validated).")

        # Session
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })

    def _get_jwt(self):
        payload = {
            "iss": self.issuer,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        token = jwt.encode(payload, self.pkey, algorithm="ES256", headers={"kid": self.kid})
        return token

    def _request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_jwt()}"
        try:
            r = self.session.request(method, url, headers=headers, **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error on request to {url}: {e}")
            raise

    # --- Advanced Trade API Endpoints ---
    def get_accounts(self):
        return self._request("GET", "/api/accounts")

    def get_positions(self):
        return self._request("GET", "/api/positions")

    def get_orders(self):
        return self._request("GET", "/api/orders")

    def get_order(self, order_id):
        return self._request("GET", f"/api/orders/{order_id}")

    def place_order(self, account_id, side, product_id, size, price=None, order_type="market"):
        data = {
            "account_id": account_id,
            "side": side,
            "product_id": product_id,
            "type": order_type,
            "size": size,
        }
        if price and order_type != "market":
            data["price"] = price
        return self._request("POST", "/api/orders", json=data)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/api/orders/{order_id}")
