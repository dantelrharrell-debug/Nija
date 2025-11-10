# nija_client.py
import os
import json
import requests
from loguru import logger
from jwt import encode
from time import time

class CoinbaseClient:
    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        self.advanced = advanced
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE") if advanced else os.getenv("COINBASE_BASE")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")

        if not self.base_url or not self.iss or not self.pem_content:
            raise ValueError("Missing COINBASE env vars (COINBASE_ISS, COINBASE_PEM_CONTENT, COINBASE_ADVANCED_BASE)")

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url}")

    def _jwt_headers(self):
        payload = {
            "iss": self.iss,
            "iat": int(time()),
            "exp": int(time()) + 30
        }
        token = encode(payload, self.pem_content, algorithm="ES256")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request(self, method, path, **kwargs):
        url = self.base_url.rstrip("/") + path
        headers = self._jwt_headers()
        try:
            if method.upper() == "GET":
                r = requests.get(url, headers=headers, **kwargs)
            else:
                r = requests.request(method, url, headers=headers, **kwargs)
            if self.debug:
                logger.debug(f"[DEBUG] {method} {url} -> {r.status_code}")
            r.raise_for_status()
            return r.status_code, r.json()
        except requests.HTTPError as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None
        except json.JSONDecodeError:
            logger.warning(f"HTTP request returned invalid JSON for {url}")
            return None, None

    def fetch_advanced_accounts(self):
        # Candidate endpoints
        endpoints = [
            "/v2/accounts",
            "/v2/brokerage/accounts",
            "/accounts",  # old paths if still supported
            "/api/v3/trading/accounts",
            "/api/v3/portfolios"
        ]
        for ep in endpoints:
            status, data = self._request("GET", ep)
            if status and data:
                logger.info(f"✅ Found working endpoint: {ep}")
                return data.get("data", data)  # return data list if available
            else:
                logger.warning(f"{ep} returned no data or failed")
        logger.error("Failed to fetch accounts from all candidate endpoints")
        return []
