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
    Coinbase Advanced (JWT) + fallback Classic shim.
    Expects env:
      - COINBASE_ISS
      - COINBASE_PEM_CONTENT  (the PEM with real newlines)
      - optional: COINBASE_ADVANCED_BASE or COINBASE_BASE
      - optional: DEBUG True/False via LOG_LEVEL or DEBUG env
    """

    def __init__(self, advanced=True, debug=False):
        self.debug = debug or os.getenv("DEBUG", "0") in ("1", "True", "true")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # prefer explicit advanced base then generic COINBASE_BASE
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE") or os.getenv("COINBASE_BASE") or ("https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com")
        self.advanced = advanced

        # state
        self._jwt_token = None
        self._jwt_exp = 0
        self.failed_endpoints = set()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

    # ----- JWT helper for Advanced Service Key -----
    def _generate_jwt(self):
        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing")

        # fast-cache: reuse token if not expired
        now = int(time.time())
        if self._jwt_token and self._jwt_exp - 10 > now:
            return self._jwt_token

        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode() if isinstance(self.pem_content, str) else self.pem_content,
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.exception("Failed to load PEM private key for JWT.")
            raise

        payload = {"iss": self.iss, "iat": now, "exp": now + 300}
        token = jwt.encode(payload, private_key, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode()
        self._jwt_token = token
        self._jwt_exp = now + 300
        if self.debug:
            logger.info("[DEBUG] Generated new JWT token (exp in 300s)")
        return token

    # ----- low level request that handles Advanced auth -----
    def request(self, method="GET", path="/", json_body=None, timeout=10):
        # normalize base + path
        if not self.base_url:
            raise ValueError("base_url not configured")
        url = self.base_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")

        headers = {"Accept": "application/json"}
        # attach JWT bearer for advanced mode if PEM exists
        if self.advanced and self.pem_content and self.iss:
            try:
                token = self._generate_jwt()
                headers["Authorization"] = f"Bearer {token}"
            except Exception:
                # let request proceed without JWT so we can observe 4xx/5xx
                logger.warning("Proceeding without JWT; check COINBASE_ISS and COINBASE_PEM_CONTENT")

        if self.debug:
            logger.info(f"[DEBUG] Request -> {method} {url} headers={list(headers.keys())}")

        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
            # Try to decode JSON safely — if it's not JSON, return text
            try:
                data = r.json()
            except Exception:
                data = r.text
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} | body_preview: {str(data)[:200]}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    # ----- attempts to discover a working accounts endpoint (Advanced) -----
    def fetch_advanced_accounts(self):
        # endpoints observed in docs / logs
        paths = [
            "/api/v3/trading/accounts",
            "/api/v3/portfolios",
            "/api/v3/accounts",
            "/v3/accounts",
            "/v2/accounts",
            "/accounts"
        ]
        for p in paths:
            if p in self.failed_endpoints:
                if self.debug: logger.debug(f"Skipping previously failed {p}")
                continue
            status, data = self.request("GET", p)
            # 200 => try extract accounts
            if status == 200 and data:
                accounts = []
                if isinstance(data, dict):
                    # common shapes
                    if "data" in data and isinstance(data["data"], list):
                        accounts = data["data"]
                    elif "accounts" in data and isinstance(data["accounts"], list):
                        accounts = data["accounts"]
                    elif "items" in data and isinstance(data["items"], list):
                        accounts = data["items"]
                    else:
                        # sometimes the root dict is the account list disguised
                        # fallback: attempt to find list children
                        for v in data.values():
                            if isinstance(v, list):
                                accounts = v
                                break
                elif isinstance(data, list):
                    accounts = data

                logger.info(f"Fetched {len(accounts)} accounts from {p}")
                return accounts
            # non-200: mark fail and continue
            if status is None or status >= 400:
                logger.warning(f"{p} returned {status}; marking as failed")
                self.failed_endpoints.add(p)
        logger.error("Failed to fetch accounts. No advanced endpoint succeeded.")
        return []

    # ----- classic spot fallback -----
    def fetch_spot_accounts(self):
        paths = ["/v2/accounts", "/accounts"]
        for p in paths:
            if p in self.failed_endpoints:
                continue
            status, data = self.request("GET", p)
            if status == 200 and data:
                if isinstance(data, dict) and "data" in data:
                    accounts = data["data"]
                elif isinstance(data, list):
                    accounts = data
                else:
                    accounts = []
                logger.info(f"Fetched {len(accounts)} spot accounts from {p}")
                return accounts
            logger.debug(f"Spot endpoint {p} returned {status}")
        logger.error("Failed to fetch spot accounts.")
        return []
