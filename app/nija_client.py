# app/nija_client.py
import os
import time
import json
import requests
import jwt
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client supporting:
      - Advanced (JWT/service key) via COINBASE_ISS + COINBASE_PEM_CONTENT + COINBASE_ADVANCED_BASE
      - Classic (HMAC) via COINBASE_API_KEY + COINBASE_API_SECRET (+ optional COINBASE_API_PASSPHRASE)
    Accepts advanced=True/False and debug flag.
    """
    def __init__(self, advanced=True, debug=False, base=None):
        self.debug = bool(debug)
        self.advanced_requested = bool(advanced)
        # allow override of base via env or constructor
        self.base = base or (os.getenv("COINBASE_ADVANCED_BASE") if advanced else os.getenv("COINBASE_BASE"))
        # standard creds
        self.std_key = os.getenv("COINBASE_API_KEY")
        self.std_secret = os.getenv("COINBASE_API_SECRET")
        self.std_pass = os.getenv("COINBASE_API_PASSPHRASE", "")
        # advanced creds
        self.iss = os.getenv("COINBASE_ISS")
        # allow either raw pem with newlines or escaped \n sequences
        pem_raw = os.getenv("COINBASE_PEM_CONTENT", "")
        self.pem_content = pem_raw.replace("\\n", "\n") if pem_raw else ""
        # backward-compatible base default
        if not self.base:
            # choose reasonable default for advanced path
            self.base = "https://api.cdp.coinbase.com" if self.advanced_requested else "https://api.coinbase.com"

        # internal
        self.token = None

        logger.info(f"CoinbaseClient init. advanced_requested={self.advanced_requested} base={self.base} debug={self.debug}")

        # pick auth mode
        if self.advanced_requested and self.iss and self.pem_content:
            # try advanced (JWT)
            try:
                self._generate_jwt()
                self.auth_mode = "advanced"
                logger.info("Auth mode: advanced (JWT/service key).")
            except Exception as e:
                logger.warning(f"Advanced JWT generation failed: {e}")
                self.auth_mode = None
        elif self.std_key and self.std_secret:
            self.auth_mode = "standard"
            logger.info("Auth mode: standard (HMAC).")
        else:
            self.auth_mode = None
            raise ValueError("No valid Coinbase API found. Check your keys (COINBASE_ISS+COINBASE_PEM_CONTENT or COINBASE_API_KEY+COINBASE_API_SECRET).")

    def _generate_jwt(self):
        payload = {"iss": self.iss, "iat": int(time.time()), "exp": int(time.time()) + 300}
        try:
            # jwt.encode returns str in PyJWT
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        except Exception as e:
            # give a clearer error when PEM invalid
            raise ValueError(f"Unable to generate JWT from PEM content: {e}")

    def _headers(self, extra=None):
        hdr = {"Accept": "application/json"}
        if self.auth_mode == "advanced":
            hdr["Authorization"] = f"Bearer {self.token}"
            hdr["Content-Type"] = "application/json"
        elif self.auth_mode == "standard":
            # standard HMAC path normally requires signing per endpoint.
            # For simple account listing endpoint we can still try using API key header
            hdr["CB-ACCESS-KEY"] = self.std_key
            if self.std_pass:
                hdr["CB-ACCESS-PASSPHRASE"] = self.std_pass
        if extra:
            hdr.update(extra)
        return hdr

    def _request(self, method, path, **kwargs):
        url = self.base.rstrip("/") + path
        headers = self._headers(kwargs.pop("headers", None))
        try:
            r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code}")
            # If non-JSON body, attempt to show it safely in debug
            try:
                data = r.json() if r.content else None
            except Exception:
                data = r.text[:400] if r.text else None
                if self.debug:
                    logger.info(f"[DEBUG] Non-JSON response: {data}")
            # Let caller inspect status code by returning (status, data)
            return r.status_code, data
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    # Candidate endpoints for advanced account info (CDP docs vary by account type)
    def fetch_advanced_accounts(self):
        candidates = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts", "/api/v3/trading/accounts", "/api/v3/portfolios"]
        for p in candidates:
            status, data = self._request("GET", p)
            if status == 200 and data:
                logger.info(f"Found working endpoint: {p}")
                # normalize: many responses wrap in {"data": [...]}
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data
            elif status is not None:
                logger.warning(f"{p} -> {status}")
        logger.error("No advanced endpoint returned 200. Check COINBASE_ADVANCED_BASE, key permissions, and paths.")
        return []

    def fetch_standard_accounts(self):
        # Try the standard account paths for classic API
        candidates = ["/v2/accounts", "/accounts"]
        for p in candidates:
            status, data = self._request("GET", p)
            if status == 200 and data:
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data
            elif status is not None:
                logger.warning(f"{p} -> {status}")
        logger.error("No standard account endpoint returned 200. Check COINBASE_BASE, API key permissions.")
        return []

    def get_accounts(self):
        if self.auth_mode == "advanced":
            return self.fetch_advanced_accounts()
        elif self.auth_mode == "standard":
            return self.fetch_standard_accounts()
        else:
            raise ValueError("No auth mode configured")

    def validate_key(self):
        """Return True if any account endpoint returned data."""
        accounts = self.get_accounts()
        if accounts:
            logger.info("API key validated: accounts returned.")
            return True
        logger.error("API key validation failed: no accounts returned.")
        return False
