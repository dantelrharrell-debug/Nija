import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Advanced Coinbase client (JWT / Service Key)
    """

    def __init__(self, debug=True):
        self.debug = debug
        self.iss = os.getenv("COINBASE_ISS")  # API Key ID
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT not set in environment")

        logger.info(f"CoinbaseClient initialized. base={self.base_url} debug={self.debug}")

    def _generate_jwt(self, method, path):
        """Create ES256 JWT for Advanced API"""
        now = int(time.time())
        payload = {
            "iss": self.iss,
            "iat": now,
            "exp": now + 60,
            "sub": "user",
            "path": path,
            "method": method
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        return token

    def _request(self, method, path, json_body=None):
        url = self.base_url.rstrip("/") + path
        token = self._generate_jwt(method, path)
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2023-11-10",  # or current date
            "Content-Type": "application/json"
        }

        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=15)
            if r.status_code >= 400:
                logger.warning(f"[{r.status_code}] {method} {url} -> {r.text}")
                return r.status_code, None
            data = r.json() if r.content else None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        """Fetch all accounts using Advanced API"""
        path = "/accounts"
        status, data = self._request("GET", path)
        if status != 200 or not data:
            logger.warning("Failed to fetch accounts from Advanced API")
            return []
        return data.get("data", data)  # Coinbase wraps in 'data'

# -------------------
# Quick test
# -------------------
if __name__ == "__main__":
    client = CoinbaseClient(debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
