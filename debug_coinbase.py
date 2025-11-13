import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClientDebug:
    def __init__(self):
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem = os.environ.get("COINBASE_PEM_CONTENT")
        self.api_key = os.environ.get("COINBASE_API_KEY")  # used as JWT 'kid'
        self.api_url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}/accounts"

        logger.info("Initializing CoinbaseClientDebug...")
        logger.info("Org ID: {}", self.org_id)
        logger.info("PEM length: {}", len(self.pem) if self.pem else 0)
        logger.info("API Key (kid): {}", self.api_key)

    def _generate_jwt(self):
        if not self.pem or not self.api_key or not self.org_id:
            logger.error("Missing PEM, API key, or org ID!")
            return None

        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes
            "sub": self.org_id
        }
        headers = {"kid": self.api_key}

        try:
            token = jwt.encode(payload, self.pem, algorithm="ES256", headers=headers)
            logger.info("Generated JWT (first 50 chars): {}", token[:50])
            return token
        except Exception as e:
            logger.exception("JWT generation failed: {}", e)
            return None

    def get_accounts(self):
        token = self._generate_jwt()
        if not token:
            logger.error("Cannot fetch accounts: JWT generation failed")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-01"
        }

        try:
            resp = requests.get(self.api_url, headers=headers)
            logger.info("HTTP Status Code: {}", resp.status_code)
            logger.info("Response Body: {}", resp.text)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error("HTTPError: {}", e)
        except Exception as e:
            logger.exception("Unexpected error fetching accounts: {}", e)

if __name__ == "__main__":
    client = CoinbaseClientDebug()
    client.get_accounts()
