import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase Advanced API client (JWT / Service Key) for Nija Trading Bot
    """
    def __init__(self, debug=True):
        self.debug = debug

        # Load credentials from environment
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in .env")

        logger.info(f"CoinbaseClient initialized. base={self.base_url} debug={self.debug}")

    def _generate_jwt(self, method="GET", path="/", body=None):
        """
        Generate signed JWT for Advanced API
        """
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 60,
            "sub": self.iss,
            "path": path,
            "method": method,
            "body": body or ""
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        return token

    def request(self, method="GET", path="/v3/accounts", json_body=None):
        """
        Make request to Coinbase Advanced API
        """
        url = self.base_url.rstrip("/") + path
        token = self._generate_jwt(method, path, body=json_body or "")
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-10",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            data = r.json() if r.content else None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        """
        Fetch all accounts from Coinbase Advanced API
        """
        status, data = self.request("GET", "/v3/accounts")
        if status == 200 and data:
            return data.get("data", data)
        else:
            logger.warning(f"Failed to fetch accounts, status={status}, data={data}")
            return []

# Simple test when running standalone
if __name__ == "__main__":
    client = CoinbaseClient(debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
