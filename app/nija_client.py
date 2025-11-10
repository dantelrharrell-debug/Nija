import os
import time
import requests
import jwt
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase Advanced / Classic client.
    Advanced (JWT/service key) is default.
    """

    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        self.advanced = advanced

        # Classic API keys (optional)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

        # Advanced service key / JWT
        self.iss = os.getenv("COINBASE_ISS")                # API key ID
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")  # Private key

        # Base URL for advanced trading
        self.base_url = os.getenv(
            "COINBASE_BASE",
            "https://api.coinbase.com/api/v3/brokerage" if advanced else "https://api.coinbase.com"
        )

        self.failed_endpoints = set()
        self.detected_permissions = {}
        self.token = None

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

        # generate JWT token if advanced
        if self.advanced:
            self._generate_jwt()

    def _generate_jwt(self):
        """
        Generate JWT token for service key auth
        """
        if not self.iss or not self.pem_content:
            logger.warning("Missing ISS or PEM for advanced API")
            return

        import datetime
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 30,  # short-lived token
            "iss": self.iss,
        }
        try:
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            if self.debug:
                logger.info(f"[DEBUG] JWT generated: {self.token[:20]}...")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            self.token = None

    def request(self, method="GET", path="/", headers=None, json_body=None, timeout=10):
        url = self.base_url.rstrip("/") + path
        hdrs = headers.copy() if headers else {}
        hdrs.setdefault("Accept", "application/json")
        if self.advanced and self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=timeout)
            try:
                data = r.json() if r.content else None
            except Exception:
                logger.warning(f"Failed parsing JSON from {url}: {r.text}")
                data = None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Fetch accounts via advanced API
        """
        status, body = self.request("GET", "/accounts")
        if status == 200 and body:
            accounts = body.get("data") if isinstance(body, dict) else body
            logger.info(f"Fetched {len(accounts)} accounts")
            return accounts
        logger.warning(f"Failed to fetch accounts: status={status} body={body}")
        return []

    def place_order(self, product_id, side, order_type, size, price=None):
        """
        Place an order via advanced API
        """
        payload = {
            "product_id": product_id,
            "side": side,  # "buy" or "sell"
            "type": order_type,  # "market" or "limit"
            "size": size
        }
        if price and order_type == "limit":
            payload["price"] = price
        status, body = self.request("POST", "/orders", json_body=payload)
        if status == 201:
            logger.info(f"Order placed successfully: {body}")
            return body
        else:
            logger.warning(f"Failed to place order: status={status} body={body}")
            return None
