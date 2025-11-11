# app/nija_client.py
import os
import time
import requests
import jwt
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

class CoinbaseClient:
    """
    Coinbase Advanced (service key / JWT) client.
    Expects env vars:
      - COINBASE_ISS
      - COINBASE_PEM_CONTENT (PEM text; can contain literal \n)
      - COINBASE_ADVANCED_BASE (optional; default https://api.cdp.coinbase.com)
    """

    def __init__(self, advanced=True, debug=False, base=None):
        self.debug = bool(debug)
        self.advanced = bool(advanced)
        self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.iss = os.getenv("COINBASE_ISS", "").strip()
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT", "")
        if "\\n" in self.pem_content:
            self.pem_content = self.pem_content.replace("\\n", "\n")
        self.pem_content = self.pem_content.strip()
        self.token = None

        if self.advanced:
            if not self.iss or not self.pem_content:
                raise ValueError("Missing COINBASE env vars: COINBASE_ISS and/or COINBASE_PEM_CONTENT")
            self._generate_jwt()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base} debug={self.debug}")

    def _generate_jwt(self):
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300
        }
        try:
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            logger.info("JWT generated successfully.")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _request(self, method, endpoint, **kwargs):
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = self.base.rstrip("/") + endpoint
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            if self.debug:
                logger.info(f"[DEBUG] {method.upper()} {url} -> {r.status_code}")
            if r.status_code == 404:
                logger.warning(f"HTTP request failed for {url}: 404 Not Found")
                return None
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                logger.warning(f"HTTP request returned non-JSON for {url}")
                return None
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None

    def fetch_advanced_accounts(self):
        endpoints = ["/accounts", "/brokerage/accounts"]
        for ep in endpoints:
            data = self._request("GET", ep)
            if data:
                logger.info(f"Accounts fetched successfully from endpoint: {ep}")
                return data
            else:
                logger.warning(f"{ep} returned no data or failed")
        logger.error("Failed to fetch accounts from all candidate endpoints")
        return None

    def validate_key(self):
        data = self.fetch_advanced_accounts()
        if data is None:
            logger.error("API key invalid or base URL incorrect. Check COINBASE env and key permissions.")
            return False
        logger.info("API key validated successfully.")
        return True
