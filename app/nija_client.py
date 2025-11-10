# app/nija_client.py
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
    Robust Coinbase client supporting:
      - Advanced (service-key / JWT) using COINBASE_ISS + COINBASE_PEM_CONTENT
      - Fallback to classic API (HMAC headers) using COINBASE_API_KEY / COINBASE_API_SECRET
    It probes a set of common endpoints and logs the raw response when JSON parsing fails.
    """
    def __init__(self, advanced=True, debug=False):
        self.debug = bool(debug)
        # JWT (advanced) credentials
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # classic HMAC credentials (optional fallback)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
        # base URL (explicit override allowed)
        self.base_url = os.getenv("COINBASE_BASE") or os.getenv("COINBASE_ADVANCED_BASE") or ("https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com")
        self.advanced = advanced

        # internal tracking
        self.failed_endpoints = set()
        self.detected_permissions = {}
        self.token = None

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

        # If advanced is chosen and we have a PEM, try to build JWT immediately (non-fatal)
        if self.advanced and self.pem_content and self.iss:
            try:
                self.token = self._generate_jwt()
            except Exception as e:
                logger.warning(f"JWT creation failed at init (non-fatal): {e}")

        # lightweight probe
        try:
            self.detect_api_permissions()
        except Exception as e:
            logger.warning(f"detect_api_permissions raised (non-fatal): {e}")

    def _generate_jwt(self):
        # Use COINBASE_PEM_CONTENT (must contain real newlines)
        priv = self.pem_content
        if not priv:
            raise ValueError("COINBASE_PEM_CONTENT missing")
        key = serialization.load_pem_private_key(priv.encode(), password=None, backend=default_backend())
        payload = {"iss": self.iss, "iat": int(time.time()), "exp": int(time.time()) + 300}
        token = jwt.encode(payload, key, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode()
        logger.info("JWT generated successfully.")
        return token

    def _build_headers(self, extra=None):
        hdrs = {"Accept": "application/json"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        # classic HMAC headers (best-effort — not a full CB HMAC implementation)
        if self.api_key and self.api_secret:
            hdrs.setdefault("CB-ACCESS-KEY", self.api_key)
            hdrs.setdefault("CB-ACCESS-SIGN", self.api_secret)
            hdrs.setdefault("CB-ACCESS-PASSPHRASE", self.api_passphrase)
        if extra:
            hdrs.update(extra)
        return hdrs

    def _request(self, method="GET", path="/", json_body=None, timeout=10):
        url = (self.base_url or "").rstrip("/") + path
        headers = self._build_headers()
        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

        # Try to parse JSON, but if it fails return raw text and log
        try:
            data = r.json()
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} | JSON OK")
            return r.status_code, data
        except Exception as e:
            # not JSON — log raw response for diagnostics
            text = r.text[:1000] if r.text else "<no-body>"
            logger.warning(f"HTTP request returned non-JSON for {url}: status={r.status_code} parse_err={e} body_preview={text!r}")
            return r.status_code, r.text

    def detect_api_permissions(self):
        # Probe a list of candidate account endpoints
        candidate_paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts", "/api/v3/trading/accounts"]
        for p in candidate_paths:
            status, body = self._request("GET", p)
            if status == 200:
                logger.info(f"Probe {p} succeeded")
                self.detected_permissions["accounts_path"] = p
                return
            else:
                logger.debug(f"Probe {p} -> {status}")
                self.failed_endpoints.add(p)
        logger.info("detect_api_permissions: no accounts endpoint succeeded during probe")

    def fetch_advanced_accounts(self):
        paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts", "/api/v3/trading/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                logger.debug(f"Skipping failed endpoint {path}")
                continue
            status, body = self._request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else (body if isinstance(body, list) else [])
                logger.info(f"Fetched {len(accounts)} records from {path}")
                return accounts
            if status is None or (isinstance(status, int) and status >= 400):
                logger.debug(f"{path} returned {status}; marking failed")
                self.failed_endpoints.add(path)
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

    def fetch_spot_accounts(self):
        # classic spot endpoints
        paths = ["/v2/accounts", "/accounts"]
        for p in paths:
            if p in self.failed_endpoints:
                continue
            status, body = self._request("GET", p)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else (body if isinstance(body, list) else [])
                logger.info(f"Fetched {len(accounts)} spot accounts from {p}")
                return accounts
        logger.error("Failed to fetch spot accounts.")
        return []
