import os
import time
import json
import requests
import jwt
from loguru import logger
from datetime import datetime, timedelta

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        self.advanced = advanced
        self.base_url = os.getenv("COINBASE_ADVANCED_BASE" if advanced else "COINBASE_BASE")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.token = None
        self.failed_endpoints = set()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

    def _get_jwt(self, method="GET", path="/v2/accounts"):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 30,
            "sub": self.iss,
            "path": path,
            "method": method,
            "body": ""
        }
        key = self.pem_content
        token = jwt.encode(payload, key, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode()
        return token

    def _request(self, method="GET", path="/v2/accounts"):
        url = self.base_url.rstrip("/") + path
        headers = {}
        if self.advanced:
            token = self._get_jwt(method, path)
            headers["CB-ACCESS-JWT"] = token
        headers["Accept"] = "application/json"
        try:
            r = requests.request(method, url, headers=headers, timeout=10)
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} {r.text}")
            data = r.json() if r.content else None
            return r.status_code, data
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error for {url}: {e}")
            return None, r.text
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        # Try Advanced endpoint first
        for path in ["/v2/accounts"]:
            status, data = self._request("GET", path)
            if status == 200:
                return data.get("data", data)
            self.failed_endpoints.add(path)
        logger.warning("Failed to fetch accounts from all endpoints.")
        return []

if __name__ == "__main__":
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)
