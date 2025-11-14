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
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")
        self.base_url = "https://api.coinbase.com"  # Advanced API base
        self.jwt_token = None

        if not all([self.org_id, self.api_key, self.pem_raw]):
            logger.error("Missing one or more required env vars: COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_CONTENT")
            raise Exception("Missing Coinbase credentials")
        
        self.connect()

    def generate_jwt(self, sub_override=None):
        now = int(time.time())
        sub_claim = sub_override or f"organizations/{self.org_id}/apiKeys/{self.api_key}"
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 min expiry
            "sub": sub_claim
        }

        try:
            token = jwt.encode(payload, self.pem_raw, algorithm="ES256")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

        return token

    def connect(self):
        # Try with standard sub format first
        self.jwt_token = self.generate_jwt()
        headers = {"Authorization": f"Bearer {self.jwt_token}"}

        resp = requests.get(f"{self.base_url}/v2/accounts", headers=headers)
        if resp.status_code == 401:
            logger.warning("401 Unauthorized with full sub format. Trying short sub format...")
            # Try simple sub claim
            self.jwt_token = self.generate_jwt(sub_override=self.api_key)
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            resp = requests.get(f"{self.base_url}/v2/accounts", headers=headers)
        
        logger.info(f"Coinbase /accounts response: {resp.status_code} {resp.text}")
        if resp.status_code != 200:
            raise Exception("Failed to connect to Coinbase API: check keys, org_id, and PEM format")

        logger.info("Coinbase connection successful!")

# For testing
if __name__ == "__main__":
    client = CoinbaseClient()
