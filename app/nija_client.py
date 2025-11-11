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
    Minimal Coinbase "Advanced" (JWT/service key) client.
    Accepts the kwargs your start_bot uses: advanced and debug.
    Expects these env vars (for advanced JWT mode):
      - COINBASE_ISS
      - COINBASE_PEM_CONTENT  (PEM text; can contain literal \n, we normalize)
      - COINBASE_ADVANCED_BASE (optional; default https://api.cdp.coinbase.com)
    """

    def __init__(self, advanced=True, debug=False, base=None):
        self.debug = bool(debug)
        self.advanced = bool(advanced)
        # allow explicit base override (for testing) else use env or default
        self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        # key identifier and pem content
        self.iss = os.getenv("COINBASE_ISS", "").strip()
        # Allow PEM stored with literal '\n' sequences; normalize to real newlines
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT", "")
        # if someone pasted the PEM with escaped newlines, fix that
        if "\\n" in self.pem_content:
            self.pem_content = self.pem_content.replace("\\n", "\n")
        self.pem_content = self.pem_content.strip()

        # token placeholder
        self.token = None

        # validate required env for advanced mode
        if self.advanced:
            if not self.iss or not self.pem_content:
                raise ValueError("Missing COINBASE env vars: COINBASE_ISS and/or COINBASE_PEM_CONTENT")

            # try generate JWT immediately (fail fast if key invalid)
            self._generate_jwt()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base} debug={self.debug}")

    def _generate_jwt(self):
        """Generate short-lived JWT for Coinbase Advanced API"""
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300  # short expiry
        }
        try:
            # jwt.encode returns str in PyJWT
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            logger.info("JWT generated successfully.")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            # raise so caller (start_bot) will exit and show message in logs
            raise

    def _request(self, method, endpoint, **kwargs):
        """Low-level request; returns parsed json or None on error"""
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = self.base.rstrip("/") + endpoint
        headers = {"Authorization": f"Bearer {self.token}"}

        # optional debug header printed to logs
        try:
            r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            if self.debug:
                logger.info(f"[DEBUG] {method.upper()} {url} -> {r.status_code}")
            # handle 404 specially (we probe multiple endpoints)
            if r.status_code == 404:
                logger.warning(f"HTTP request failed for {url}: 404 Not Found")
                return None
            r.raise_for_status()
            # attempt to parse json
            try:
                return r.json()
            except ValueError:
                logger.warning(f"HTTP request returned non-JSON for {url}")
                return None
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None

    def fetch_advanced_accounts(self):
        """
        Probe a small set of likely Advanced endpoints and return the first that returns data.
        Returns dict (parsed JSON) or None.
        """
        endpoints = [
            "/accounts",            # primary
            "/brokerage/accounts",  # if brokerage access exists
        ]
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
        """Simple health check wrapper"""
        data = self.fetch_advanced_accounts()
        if data is None:
            logger.error("API key invalid or base URL incorrect. Check COINBASE env and key permissions.")
            return False
        logger.info("API key validated successfully.")
        return True
