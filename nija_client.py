# nija_client.py
import os
import time
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client for Advanced (JWT/service key) Coinbase API.
    """
    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.advanced = advanced

        # For internal tracking
        self.failed_endpoints = set()
        self.detected_permissions = {}
        self.token = None  # Placeholder for JWT if implemented

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

    def _request(self, method="GET", path="/", headers=None, json_body=None, timeout=10):
        url = self.base_url.rstrip("/") + path
        hdrs = headers or {}
        hdrs.setdefault("Accept", "application/json")
        # If JWT is required, include it here (currently placeholder)
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"

        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=timeout)
            data = r.json() if r.content else None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        """
        Fetch accounts from Advanced Coinbase API.
        """
        status, data = self._request("GET", "/accounts")
        if status == 200 and data:
            return data.get("data", [])
        logger.warning(f"Failed to fetch accounts, status={status}, data={data}")
        return []

    # Example order placement method (ready for live trading)
    def place_order(self, account_id, side, product_id, size, price=None, order_type="market"):
        """
        Place a market or limit order.
        """
        payload = {
            "account_id": account_id,
            "side": side,
            "product_id": product_id,
            "size": size,
            "type": order_type
        }
        if price and order_type == "limit":
            payload["price"] = price

        status, data = self._request("POST", "/orders", json_body=payload)
        if status == 201:
            logger.info(f"Order placed successfully: {data}")
        else:
            logger.warning(f"Failed to place order: status={status}, data={data}")
        return data
