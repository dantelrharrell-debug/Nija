import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# ==========================
# Load .env for local/dev
# ==========================
load_dotenv()

# ==========================
# Environment variables
# ==========================
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not API_KEY_ID or not PEM or not ORG_ID:
    logger.error(
        "Missing one or more required environment variables: "
        "COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID"
    )
    # Prevent crash, set dummy defaults
    API_KEY_ID = API_KEY_ID or "dummy_key"
    PEM = PEM or "-----BEGIN EC PRIVATE KEY-----\nMISSING\n-----END EC PRIVATE KEY-----"
    ORG_ID = ORG_ID or "dummy_org"

# ==========================
# Load private key
# ==========================
try:
    private_key = serialization.load_pem_private_key(
        PEM.encode(), password=None, backend=default_backend()
    )
    logger.info("Private key loaded successfully")
except Exception as e:
    logger.exception(f"Failed to load private key: {e}")
    # Use dummy key to prevent crash
    private_key = None

# ==========================
# CoinbaseClient class
# ==========================
class CoinbaseClient:
    def __init__(self, api_key, org_id, private_key):
        self.api_key = api_key
        self.org_id = org_id
        self.private_key = private_key

    def _generate_jwt(self, path, method="GET"):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 120,
            "sub": self.api_key,
            "request_path": path,
            "method": method
        }
        headers = {"alg": "ES256", "kid": self.api_key}
        try:
            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            return token
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            return "dummy_token"

    def get_accounts(self):
        path = f"/api/v3/brokerage/organizations/{self.org_id}/accounts"
        url = f"https://api.coinbase.com{path}"
        token = self._generate_jwt(path)
        try:
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": "2025-11-12"
            })
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching accounts: {e} | Response: {e.response.text if e.response else 'No response'}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error fetching accounts: {e}")
            return None

# ==========================
# Bot main function
# ==========================
def start_bot_main():
    logger.info("Nija bot starting...")
    client = CoinbaseClient(API_KEY_ID, ORG_ID, private_key)
    while True:
        accounts_resp = client.get_accounts()
        if accounts_resp:
            logger.info(f"Fetched accounts: {accounts_resp}")
        else:
            logger.warning("Accounts fetch failed, will retry next heartbeat.")
        logger.info("heartbeat")
        time.sleep(5)  # heartbeat interval

# ==========================
# Entry point
# ==========================
if __name__ == "__main__":
    try:
        start_bot_main()
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception(f"Unexpected bot crash: {e}")
