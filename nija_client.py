import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        # Load environment variables
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT")
        self.api_key = os.environ.get("COINBASE_API_KEY")  # used as JWT 'kid'
        self.api_url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{self.org_id}/accounts"

        logger.info("Initializing CoinbaseClient...")
        logger.info("Org ID: {}", self.org_id)
        logger.info("API Key (kid): {}", self.api_key)
        if self.pem_raw:
            logger.info("Raw PEM length: {}", len(self.pem_raw))
            self.pem = self._fix_pem(self.pem_raw)
        else:
            logger.error("PEM content missing")
            self.pem = None

    def _fix_pem(self, pem_content):
        """Ensure proper PEM formatting with line breaks."""
        pem_content = pem_content.strip()
        # Replace escaped newlines with actual newlines
        pem_content = pem_content.replace("\\n", "\n")
        if not pem_content.startswith("-----BEGIN EC PRIVATE KEY-----"):
            pem_content = "-----BEGIN EC PRIVATE KEY-----\n" + pem_content
        if not pem_content.endswith("-----END EC PRIVATE KEY-----"):
            pem_content += "\n-----END EC PRIVATE KEY-----"
        logger.info("Fixed PEM length: {}", len(pem_content))
        return pem_content

    def _generate_jwt(self):
        if not self.pem or not self.api_key or not self.org_id:
            logger.error("Cannot generate JWT: missing PEM, API key, or Org ID")
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
            print("DEBUG_JWT (first 50 chars):", token[:50])  # Print directly for verification
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
                logger.error("- Invalid PEM format (fixed automatically)")
                logger.error("- Wrong API key / kid")
                logger.error("- Org ID mismatch")
                logger.error("- Expired or malformed JWT")
            else:
                logger.error("HTTPError: {}", e)
        except Exception as e:
            logger.exception("Unexpected error fetching accounts: {}", e)
        return None

# --- TEST SCRIPT ---
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.get_accounts()
    if accounts:
        logger.info("Accounts fetched successfully!")
    else:
        logger.error("Failed to fetch accounts.")
