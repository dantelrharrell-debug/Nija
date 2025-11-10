# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client for Coinbase Advanced (JWT / Service Key) API.
    """

    def __init__(self, debug=False):
        self.debug = debug
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.iss = os.getenv("COINBASE_ISS")           # your key ID
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")  # your private key PEM

        if not self.iss or not self.pem_content:
            raise ValueError("Missing COINBASE_ISS or COINBASE_PEM_CONTENT for Advanced API")

        logger.info(f"CoinbaseClient initialized. base={self.base_url} debug={self.debug}")

    def _get_jwt(self, method="GET", path="/"):
        """
        Create JWT for Advanced API request.
        """
        iat = int(time.time())
        payload = {
            "iss": self.iss,
            "iat": iat,
            "exp": iat + 60,
            "sub": "user",
            "path": path,
            "method": method,
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        return token

    def _request(self, method="GET", path="/", json_body=None):
        url = self.base_url.rstrip("/") + path
        token = self._get_jwt(method, path)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            data = r.json() if r.content else None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} {data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        """
        Fetch Coinbase Advanced accounts using the correct endpoint.
        """
        # Use the Advanced API endpoint for trading accounts
        paths = ["/api/v3/trading/accounts", "/api/v3/portfolios"]
        for path in paths:
            status, data = self._request("GET", path)
            if status == 200 and data:
                return data.get("data", data)
        logger.warning("Failed to fetch accounts from Advanced API")
        return []

# Quick test script
if __name__ == "__main__":
    client = CoinbaseClient(debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
