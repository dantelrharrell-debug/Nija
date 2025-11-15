import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Load .env
load_dotenv()

# ==========================
# Environment variables
# ==========================
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", 5))
CB_VERSION = os.environ.get("CB_VERSION", "2025-11-12")

if not API_KEY_ID or not PEM or not ORG_ID:
    logger.error("Missing one or more required environment variables: COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID")
    exit(1)

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
    exit(1)

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
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
        return token

    def get_accounts(self):
        path = f"/api/v3/brokerage/organizations/{self.org_id}/accounts"
        url = f"https://api.coinbase.com{path}"
        token = self._generate_jwt(path)

        try:
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "CB-VERSION": CB_VERSION
            })
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.warning("401 Unauthorized. JWT may be invalid or expired.")
            logger.error(f"HTTP error fetching accounts: {e} | Response: {e.response.text if e.response else 'No response'}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error fetching accounts: {e}")
            return None

# ==========================
# Bot main loop
# ==========================
def start_bot_main():
    logger.info("Nija bot starting...")
    client = CoinbaseClient(API_KEY_ID, ORG_ID, private_key)

    while True:
        accounts_resp = client.get_accounts()
        if accounts_resp:
            logger.info(f"Fetched accounts successfully: {accounts_resp}")
        else:
            logger.warning("Accounts fetch failed, retrying at next heartbeat.")

        logger.info("heartbeat")
        time.sleep(HEARTBEAT_INTERVAL)

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
