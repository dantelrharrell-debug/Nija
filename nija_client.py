import os
import time
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Simple Coinbase client (Advanced or Classic).
    """
    def __init__(self, advanced=True, debug=True):
        self.debug = debug
        self.advanced = advanced

        # Choose base URL
        if self.advanced:
            self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        else:
            self.base_url = os.getenv("COINBASE_BASE", "https://api.coinbase.com")

        # Load keys
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")

        # Track failed endpoints
        self.failed_endpoints = set()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

    def request(self, method="GET", path="/"):
        url = self.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        try:
            r = requests.request(method, url, headers=headers, timeout=10)
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} {r.text}")
            data = r.json() if r.content else None
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for path in paths:
            status, data = self.request("GET", path)
            if status == 200 and data:
                return data.get("data", data)
            self.failed_endpoints.add(path)
        logger.warning("No accounts endpoint succeeded.")
        return []

if __name__ == "__main__":
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
