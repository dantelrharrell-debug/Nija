import os
import time
import json
import jwt  # PyJWT
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Advanced Coinbase client using JWT / Service Key.
    """

    def __init__(self, debug=True):
        self.debug = debug
        self.api_key_id = os.getenv("COINBASE_ISS")  # API key ID
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.token = None
        self.session = requests.Session()

        if not self.api_key_id or not self.pem_content:
            raise ValueError("COINBASE_ISS and COINBASE_PEM_CONTENT must be set in .env")

        logger.info(f"CoinbaseClient initialized. base={self.base_url} debug={self.debug}")

    def _generate_jwt(self):
        """
        Generate JWT token using PEM private key
        """
        timestamp = int(time.time())
        payload = {
            "iat": timestamp,
            "exp": timestamp + 60,
            "iss": self.api_key_id
        }
        try:
            token = jwt.encode(payload, self.pem_content, algorithm="ES256")
            return token
        except Exception as e:
            logger.error(f"JWT generation failed: {e}")
            return None

    def _request(self, method, path, json_body=None):
        """
        Make an authenticated request
        """
        url = self.base_url.rstrip("/") + path
        token = self._generate_jwt()
        if not token:
            logger.error("Cannot generate JWT, aborting request")
            return None, None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            r = self.session.request(method, url, headers=headers, json=json_body, timeout=10)
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code}")
                try:
                    logger.info(json.dumps(r.json(), indent=2))
                except Exception:
                    logger.info(r.text)
            data = r.json()
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    # Fetch accounts
    def fetch_accounts(self):
        status, data = self._request("GET", "/v3/accounts")
        if status == 200 and data:
            return data.get("data", [])
        return []

# Test run
if __name__ == "__main__":
    client = CoinbaseClient(debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
