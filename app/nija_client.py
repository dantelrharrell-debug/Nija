# app/nija_client.py
import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    """
    Coinbase Advanced / Brokerage client using JWT (ES256) auth.
    Base URL is configurable via COINBASE_API_BASE, otherwise uses
    the Advanced Trade brokerage default:
      https://api.coinbase.com/api/v3/brokerage/organizations/<ORG_ID>
    """

    def __init__(self):
        # env
        self.org_id = os.getenv("COINBASE_ORG_ID")
        if not self.org_id:
            raise ValueError("COINBASE_ORG_ID not set in environment")

        # base: override with COINBASE_API_BASE if you need a custom host (useful for testing)
        self.base = os.getenv(
            "COINBASE_API_BASE",
            f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}"
        ).rstrip("/")

        # JWT values
        self.kid = os.getenv("COINBASE_JWT_KID") or os.getenv("COINBASE_KEY_ID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER") or os.getenv("COINBASE_ISSUER")
        pem = os.getenv("COINBASE_JWT_PEM") or os.getenv("COINBASE_PEM_CONTENT")
        if not pem:
            raise ValueError("COINBASE_JWT_PEM (private key) not provided")

        # Try normalize (strip surrounding quotes that sometimes appear in env)
        if pem.startswith('"') and pem.endswith('"'):
            pem = pem[1:-1].replace('\\n', '\n')

        self._pem_string = pem
        self._load_and_validate_pem()

        # HTTP session
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        logger.info("CoinbaseClient initialized. base=%s", self.base)

    def _load_and_validate_pem(self):
        try:
            # Load private key using cryptography (validates formatting)
            self._private_key = serialization.load_pem_private_key(
                self._pem_string.encode("utf-8"),
                password=None,
                backend=default_backend()
            )
            logger.debug("PEM validation via cryptography succeeded.")
        except Exception as e:
            logger.error("PEM validation failed: %s", e)
            raise

        if not self.kid or not self.issuer:
            logger.error("COINBASE_JWT_KID or COINBASE_JWT_ISSUER missing")
            raise ValueError("COINBASE_JWT_KID and COINBASE_JWT_ISSUER must be set")

    def _generate_jwt(self, lifetime_seconds: int = 300) -> str:
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + lifetime_seconds,
            "iss": self.issuer,
        }
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers={"kid": self.kid})
        # pyjwt may return bytes on some versions
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def _request(self, method: str, path: str, params=None, json=None, retries: int = 3, timeout: int = 15):
        """
        Generic request to Coinbase Advanced API.
        `path` should start with a leading slash, e.g. "/accounts"
        """
        url = f"{self.base}{path}"
        headers = {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "Content-Type": "application/json",
            "CB-VERSION": "2025-11-12"  # optional version header for debugging
        }

        backoff = 1
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
                resp.raise_for_status()
                # if no JSON body, return text
                if resp.headers.get("Content-Type", "").startswith("application/json"):
                    return resp.json()
                return resp.text
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                logger.warning("HTTP error %s %s (attempt %d/%d): %s", status, url, attempt, retries, e)
                # Retry for 429 / 5xx / transient 404 scenarios (some paths return 404 until org provisioning)
                if attempt == retries:
                    raise
                time.sleep(backoff)
                backoff *= 2
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning("Connection/Timeout for %s (attempt %d/%d): %s", url, attempt, retries, e)
                if attempt == retries:
                    raise
                time.sleep(backoff)
                backoff *= 2
            except Exception as e:
                logger.error("Unexpected error when calling %s: %s", url, e)
                raise

    # --------------------------
    # Advanced Trade API Methods
    # --------------------------

    def get_accounts(self):
        """GET /accounts - list accounts for the organization"""
        return self._request("GET", "/accounts")

    def get_positions(self):
        """GET /positions - list positions for the org"""
        return self._request("GET", "/positions")

    def list_orders(self, params=None):
        """GET /orders - list orders"""
        return self._request("GET", "/orders", params=params)

    def get_order(self, order_id):
        """GET /orders/{id}"""
        return self._request("GET", f"/orders/{order_id}")

    def place_order(self, account_id, side, product_id, size, price=None, order_type="market"):
        """
        POST /orders
        order_type: "market" or "limit" (payload follows Advanced API shape — this is a simplified payload)
        """
        body = {
            "account_id": account_id,
            "side": side,            # "buy" or "sell"
            "product_id": product_id,
            "size": str(size),
            "type": order_type
        }
        if price is not None and order_type != "market":
            body["price"] = str(price)
        return self._request("POST", "/orders", json=body)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/orders/{order_id}")

