# app/nija_client.py
import os
import time
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client shim for both Advanced (service-key/CDP) and Classic (spot/HMAC) APIs.
    - Use COINBASE_BASE to override endpoint.
    - This file focuses on robust startup and avoids AttributeError crashes.
    """
    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        # basic env creds (optional)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
        self.iss = os.getenv("COINBASE_ISS")  # advanced service key id (optional)
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")  # advanced PEM (optional)
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com")
        self.advanced = advanced

        # *** IMPORTANT: initialize attributes used by helpers BEFORE calling them ***
        self.failed_endpoints = set()
        self.detected_permissions = {}
        self.token = None  # reserved for JWT if you later add it

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

        # run a light probe to mark endpoints that fail early (non-fatal)
        try:
            self.detect_api_permissions()
        except Exception as e:
            logger.warning(f"detect_api_permissions raised an exception (non-fatal): {e}")

    # ---------------- helper: HTTP request ----------------
    def request(self, method="GET", path="/", headers=None, json_body=None, timeout=10):
        url = self.base_url.rstrip("/") + path
        hdrs = headers or {}
        # default headers (won't break if HMAC/JWT not configured)
        hdrs.setdefault("Accept", "application/json")
        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=timeout)
            try:
                data = r.json()
            except Exception:
                data = None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    # ---------------- detect what endpoints respond ----------------
    def detect_api_permissions(self):
        """
        Lightweight probe to see which common account endpoints are available and record failures.
        This will not raise on 404s; it just records failed endpoints in self.failed_endpoints.
        """
        candidate_paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for p in candidate_paths:
            status, body = self.request("GET", p)
            if status is None:
                # network error — record and continue
                logger.debug(f"Probe {p} -> network error")
                self.failed_endpoints.add(p)
                continue
            if status == 200:
                logger.info(f"Probe {p} succeeded")
                self.detected_permissions["accounts_path"] = p
                return
            if status == 404 or status == 403 or status >= 400:
                logger.debug(f"Probe {p} returned {status}")
                self.failed_endpoints.add(p)
        logger.info("detect_api_permissions: no accounts endpoint succeeded during probe")

    # ---------------- fetch accounts (tries known endpoints) ----------------
    def fetch_advanced_accounts(self):
        """
        Try several advanced endpoints and return list of accounts or empty list.
        """
        paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                logger.debug(f"Skipping previously failed endpoint {path}")
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                # prefer common JSON shapes
                if isinstance(body, dict) and "data" in body:
                    accounts = body.get("data", [])
                elif isinstance(body, dict) and "accounts" in body:
                    accounts = body.get("accounts", [])
                else:
                    # fallback: body may already be a list
                    accounts = body if isinstance(body, list) else []
                logger.info(f"Fetched {len(accounts)} accounts from {path}")
                return accounts
            if status == 404:
                logger.warning(f"{path} returned 404; marking as failed")
                self.failed_endpoints.add(path)
            elif status is None:
                logger.warning(f"{path} returned network error; marking as failed")
                self.failed_endpoints.add(path)
            else:
                logger.debug(f"{path} returned {status}; continuing")
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

    def fetch_spot_accounts(self):
        """
        Try classic spot accounts endpoint(s).
        """
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
