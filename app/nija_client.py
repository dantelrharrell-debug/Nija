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
    Coinbase Advanced client used by the Nija bot.
    Compatible signature: CoinbaseClient(advanced=True, debug=True)
    """

    def __init__(self, advanced=True, debug=False, base=None):
        self.advanced = advanced
        self.debug = debug
        # Base URL: prefer explicit param, then env, then default advanced URL
        self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        # 'iss' is the key identifier per Coinbase Advanced JWT docs (e.g. organizations/.../apiKeys/...)
        self.iss = os.getenv("COINBASE_ISS")
        # Accept PEM sent with literal \n or with real newlines
        raw_pem = os.getenv("COINBASE_PEM_CONTENT", "")
        # Normalize common formats: if user pasted with literal "\n" replace with actual newlines
        self.pem_content = raw_pem.replace("\\n", "\n")
        self.token = None

        if not self.pem_content or not self.iss:
            raise ValueError("Missing COINBASE env vars (COINBASE_ISS, COINBASE_PEM_CONTENT)")

        # Pre-generate token (will refresh on demand)
        self._generate_jwt()
        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base}")

    def _generate_jwt(self):
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            # short-lived token is OK; set to 300s (5m)
            "exp": int(time.time()) + 300
        }
        try:
            # jwt.encode returns str in pyjwt >= 2.x
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            if isinstance(self.token, bytes):
                self.token = self.token.decode("utf-8")
        except Exception as e:
            logger.exception(f"Failed to generate JWT: {e}")
            # surface the error up so start_bot can log & exit
            raise

    def _request(self, method: str, endpoint: str, **kwargs):
        """
        Generic request helper. Returns (status_code, json_data) or (None, None) on failure.
        """
        url = self.base.rstrip("/") + endpoint
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.request(method.upper(), url, headers=headers, timeout=10, **kwargs)
            if self.debug:
                logger.debug(f"[DEBUG] {method.upper()} {url} -> {r.status_code}")
            if r.status_code == 401:
                # token might have expired — regenerate once and retry
                logger.warning("401 from Coinbase; regenerating JWT and retrying once.")
                self._generate_jwt()
                headers["Authorization"] = f"Bearer {self.token}"
                r = requests.request(method.upper(), url, headers=headers, timeout=10, **kwargs)
                if self.debug:
                    logger.debug(f"[DEBUG retry] {method.upper()} {url} -> {r.status_code}")

            # handle 404 explicitly in logs
            if r.status_code == 404:
                logger.warning(f"HTTP request failed for {url}: 404 Not Found")
                return None, None

            r.raise_for_status()
            try:
                return r.status_code, r.json()
            except ValueError:
                logger.warning(f"HTTP request returned invalid JSON for {url}")
                return r.status_code, None
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Try verified Advanced API endpoints. Stops at first successful endpoint.
        Returns list/dict from API or [] on failure.
        """
        endpoints = [
            "/accounts",               # expected for many Advanced/Prime customers
            "/brokerage/accounts",     # other possible path
            "/api/v3/trading/accounts",# sometimes present behind a base path
            "/api/v3/portfolios"
        ]

        for ep in endpoints:
            status, data = self._request("GET", ep)
            if status and data:
                logger.info(f"✅ Found working endpoint: {ep}")
                # many Coinbase responses wrap data in {"data": [...]}
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data
            else:
                logger.warning(f"{ep} returned no data or failed")
        logger.error("Failed to fetch accounts from all candidate endpoints")
        return []

    def validate_key(self):
        """
        Quick boolean check for a working key/base.
        """
        status, data = self._request("GET", "/accounts")
        if status is None:
            logger.error("API key invalid or base URL incorrect. Check permissions and COINBASE_ADVANCED_BASE.")
            return False
        logger.info("API key validated successfully.")
        return True
