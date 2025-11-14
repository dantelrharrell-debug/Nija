# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

class CoinbaseClient:
    def __init__(self):
        # Load environment variables
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")

        if not self.api_key or not self.pem_raw:
            raise ValueError("API_KEY or PEM_CONTENT missing!")

        # Clean PEM formatting
        self.pem = self.pem_raw.replace("\\n", "\n") if "\\n" in self.pem_raw else self.pem_raw

        # Base URL for Coinbase Advanced API
        self.base_url = "https://api.coinbase.com"

        # Test connection immediately
        self.test_connection()

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 60,  # 60 seconds validity
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}"
        }
        token = jwt.encode(payload, self.pem, algorithm="ES256")
        return token

    def request(self, method, path, data=None):
        url = f"{self.base_url}{path}"
        token = self.generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        response = requests.request(method, url, headers=headers, json=data)
        if response.status_code == 401:
            logger.error("Unauthorized: JWT or API key invalid!")
        return response

    def test_connection(self):
        # Simple endpoint to verify JWT works
        response = self.request("GET", "/v3/brokerage/accounts")
        if response.status_code == 200:
            logger.info("✅ Coinbase connection OK, ready to trade.")
        else:
            logger.error(f"❌ Coinbase connection failed: {response.status_code} {response.text}")

# Example usage
if __name__ == "__main__":
    client = CoinbaseClient()
