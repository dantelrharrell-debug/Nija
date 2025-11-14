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
        # Load env vars
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT", "")
        self.api_key = os.environ.get("COINBASE_API_KEY", "")

        if not self.org_id or not self.pem_raw or not self.api_key:
            raise ValueError("Missing Coinbase credentials. Check env variables.")

        # Fix escaped newlines in PEM if needed
        self.pem_fixed = self.pem_raw.replace("\\n", "\n")

        # Detect if API_KEY is full path
        if "organizations/" in self.api_key:
            self.sub = self.api_key  # full path
        else:
            self.sub = f"organizations/{self.org_id}/apiKeys/{self.api_key}"

        logger.info(f"Using sub claim: {self.sub}")

    def generate_jwt(self):
        payload = {
            "sub": self.sub,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,  # short-lived JWT
        }
        token = jwt.encode(payload, self.pem_fixed, algorithm="ES256")
        return token

    def test_auth(self):
        token = self.generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-ACCESS-SIGN": "",  # not needed for JWT auth
        }

        url = "https://api.coinbase.com/v2/accounts"  # simple read endpoint
        r = requests.get(url, headers=headers)

        logger.info(f"Coinbase status: {r.status_code}")
        if r.status_code != 200:
            logger.error(f"Response: {r.text}")
        else:
            logger.success("✅ Coinbase auth successful!")
            logger.info(r.json())

        return r.status_code, r.text

# For quick test:
if __name__ == "__main__":
    client = CoinbaseClient()
    client.test_auth()
