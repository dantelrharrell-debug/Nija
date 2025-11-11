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
        self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.iss = os.getenv("COINBASE_ISS")
        raw_pem = os.getenv("COINBASE_PEM_CONTENT", "")
        self.pem_content = raw_pem.replace("\\n", "\n")
        self.token = None

        if not self.iss or not self.pem_content:
            raise ValueError("Missing COINBASE env vars (COINBASE_ISS, COINBASE_PEM_CONTENT)")

        self._generate_jwt()
        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base}")

    def _generate_jwt(self):
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300
        }
        try:
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            if isinstance(self.token, bytes):
                self.token = self.token.decode("utf-8")
        except Exception as e:
            logger.exception(f"Failed to generate JWT: {e}")
            raise

    def _request(self, method: str, endpoint: str, **kwargs):
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
                logger.warning("401 from Coinbase; regenerating JWT and retrying once.")
                self._generate_jwt()
                headers["Authorization"] = f"Bearer {self.token}"
                r = requests.request(method.upper(), url, headers=headers, timeout=10, **kwargs)
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
        endpoints = [
            "/accounts",
            "/brokerage/accounts",
            "/api/v3/trading/accounts",
            "/api/v3/portfolios"
        ]
        for ep in endpoints:
            status, data = self._request("GET", ep)
            if status and data:
                logger.info(f"✅ Found working endpoint: {ep}")
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data
            else:
                logger.warning(f"{ep} returned no data or failed")
        logger.error("Failed to fetch accounts from all candidate endpoints")
        return []

    def validate_key(self):
        status, data = self._request("GET", "/accounts")
        if status is None:
            logger.error("API key invalid or base URL incorrect. Check permissions and COINBASE_ADVANCED_BASE.")
            return False
        logger.info("API key validated successfully.")
        return True
