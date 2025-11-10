# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt  # PyJWT

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))


class CoinbaseClient:
    """
    Coinbase Advanced (JWT ES256) + fallback shim.
    - Requires env:
        COINBASE_ISS (service key id)
        COINBASE_PEM_CONTENT (PEM private key with real newlines)
      Optional:
        COINBASE_BASE (override, defaults to https://api.cdp.coinbase.com)
    """

    def __init__(self, advanced=True, debug=False):
        self.debug = bool(debug)
        self.advanced = bool(advanced)
        # Advanced (service key) values:
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # Base URL
        default_base = "https://api.cdp.coinbase.com" if self.advanced else "https://api.coinbase.com"
        self.base_url = os.getenv("COINBASE_BASE", default_base).rstrip("/")
        # token cache
        self._token = None
        self._token_exp = 0

        # bookkeeping for probes
        self.failed_endpoints = set()
        self.detected_permissions = {}

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

        # run a lightweight probe (non-fatal)
        try:
            self.detect_api_permissions()
        except Exception as e:
            logger.warning(f"startup probe raised non-fatal exception: {e}")

    # ---------------- JWT generation for Advanced (ES256) ----------------
    def _generate_jwt(self):
        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing for advanced JWT generation")

        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.exception("Failed to load PEM private key for JWT")
            raise

        now = int(time.time())
        payload = {"iss": self.iss, "iat": now, "exp": now + 300}
        token = jwt.encode(payload, private_key, algorithm="ES256")
        # PyJWT may return bytes on some versions
        if isinstance(token, bytes):
            token = token.decode()
        # cache token
        self._token = token
        self._token_exp = now + 280  # refresh a bit early
        if self.debug:
            logger.info("[DEBUG] Generated new JWT (short-lived).")
        return token

    def _ensure_token(self):
        if not self.advanced:
            return None
        now = int(time.time())
        if self._token is None or now >= self._token_exp:
            return self._generate_jwt()
        return self._token

    # ---------------- HTTP request helper ----------------
    def request(self, method="GET", path="/v3/accounts", headers=None, json_body=None, timeout=10):
        url = f"{self.base_url.rstrip('/')}{path}"
        hdrs = {} if headers is None else dict(headers)

        hdrs.setdefault("Accept", "application/json")

        # attach Bearer token for advanced API
        if self.advanced:
            try:
                token = self._ensure_token()
            except Exception as e:
                logger.exception(f"JWT creation failed: {e}")
                # fall back to making the request without Authorization (will likely 401/403)
                token = None
            if token:
                hdrs["Authorization"] = f"Bearer {token}"

        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=timeout)
            # parse JSON safely
            try:
                body = r.json()
            except Exception:
                # body isn't JSON (or malformed). capture text for debugging.
                body = r.text
                if self.debug:
                    logger.warning(f"[DEBUG] Non-JSON response for {url!r}: {body!r}")
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> status={r.status_code}")
            return r.status_code, body
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    # ---------------- Probe to detect available endpoints ----------------
    def detect_api_permissions(self):
        candidate_paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for p in candidate_paths:
            status, body = self.request("GET", p)
            if status is None:
                # network or parsing error — record and continue
                logger.debug(f"Probe {p} -> network/parsing error")
                self.failed_endpoints.add(p)
                continue
            if status == 200:
                logger.info(f"Probe {p} succeeded")
                self.detected_permissions["accounts_path"] = p
                return
            # treat 4xx/5xx as failed but keep probing
            if status >= 400:
                logger.debug(f"Probe {p} returned {status}")
                self.failed_endpoints.add(p)
        logger.info("detect_api_permissions: no accounts endpoint succeeded during probe")

    # ---------------- fetch accounts - advanced (tries multiple paths) ----------------
    def fetch_advanced_accounts(self):
        paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                if self.debug:
                    logger.debug(f"Skipping previously failed endpoint {path}")
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                # common shapes: { "data": [...] } or { "accounts": [...] } or list
                if isinstance(body, dict):
                    if "data" in body:
                        accounts = body.get("data", [])
                    elif "accounts" in body:
                        accounts = body.get("accounts", [])
                    else:
                        # unknown dict shape -> attempt to find lists inside
                        accounts = next((v for v in body.values() if isinstance(v, list)), [])
                else:
                    accounts = body if isinstance(body, list) else []
                logger.info(f"Fetched {len(accounts)} accounts from {path}")
                return accounts
            # record failed endpoint
            if status is None or status >= 400:
                if status == 404:
                    logger.warning(f"{path} returned 404; marking as failed")
                else:
                    logger.debug(f"{path} returned status {status}")
                self.failed_endpoints.add(path)
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

    # ---------------- fetch spot accounts (classic) ----------------
    def fetch_spot_accounts(self):
        paths = ["/v2/accounts", "/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                if isinstance(body, dict) and "data" in body:
                    accounts = body.get("data", [])
                else:
                    accounts = body if isinstance(body, list) else []
                logger.info(f"Fetched {len(accounts)} spot accounts from {path}")
                return accounts
            logger.debug(f"Spot accounts {path} returned {status}")
        logger.error("Failed to fetch spot accounts.")
        return []
