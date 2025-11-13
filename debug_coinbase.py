import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClientFullDebug:
    def __init__(self):
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem = os.environ.get("COINBASE_PEM_CONTENT")
        self.api_key = os.environ.get("COINBASE_API_KEY")  # used as JWT 'kid'
        self.api_url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}/accounts"

        logger.info("Initializing CoinbaseClientFullDebug...")
        logger.info("Org ID: {}", self.org_id)
        logger.info("API Key (kid): {}", self.api_key)
        if self.pem:
            logger.info("PEM length: {}", len(self.pem))
        else:
            logger.error("PEM is missing or empty!")

    def _validate_pem(self):
        """Quick check for proper PEM format."""
        if not self.pem:
            logger.error("PEM content missing")
            return False
        if not self.pem.startswith("-----BEGIN EC PRIVATE KEY-----"):
            logger.error("PEM missing BEGIN line")
            return False
        if not self.pem.strip().endswith("-----END EC PRIVATE KEY-----"):
            logger.error("PEM missing END line")
            return False
        return True

    def _generate_jwt(self):
        if not self._validate_pem():
            return None
        if not self.api_key or not self.org_id:
            logger.error("API key or Org ID missing")
            return None

        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes expiry
            "sub": self.org_id
        }
        headers = {"kid": self.api_key}

        try:
            token = jwt.encode(payload, self.pem, algorithm="ES256", headers=headers)
            logger.info("Generated JWT successfully. Preview (first 50 chars): {}", token[:50])
            return token
        except Exception as e:
            logger.exception("JWT generation failed: {}", e)
            return None

    def get_accounts(self):
        token = self._generate_jwt()
        if not token:
            logger.error("Cannot fetch accounts: JWT generation failed")
            return None

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
            if resp.status_code == 401:
                logger.error("Unauthorized (401). Possible causes:")
                logger.error("- Invalid PEM format")
                logger.error("- Wrong API key or kid")
                logger.error("- Org ID mismatch")
                logger.error("- Expired or malformed JWT")
            else:
                logger.error("HTTPError: {}", e)
        except Exception as e:
            logger.exception("Unexpected error fetching accounts: {}", e)
        return None

if __name__ == "__main__":
    client = CoinbaseClientFullDebug()
    accounts = client.get_accounts()
    if accounts:
        logger.info("Accounts fetched successfully!")
    else:
        logger.error("Failed to fetch accounts.")import os
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
