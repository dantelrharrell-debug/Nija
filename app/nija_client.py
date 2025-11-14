# app/nija_client.py

import os
import base64
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Setup logger ---
logger.remove()
logger.add(lambda m: print(m, end=""))

# --- Decode base64 PEM and set env var ---
pem_b64 = os.environ.get("COINBASE_PEM_B64")
if not pem_b64:
    raise RuntimeError("COINBASE_PEM_B64 missing")

try:
    pem_bytes = base64.b64decode(pem_b64)
    PEM_CONTENT = pem_bytes.decode("utf-8")
except Exception as e:
    raise RuntimeError(f"Failed to decode COINBASE_PEM_B64: {e}")

os.environ["COINBASE_PEM_CONTENT"] = PEM_CONTENT

# --- Load other env vars ---
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MAX_TRADE_PERCENT = os.environ.get("MAX_TRADE_PERCENT", "5")
MIN_TRADE_PERCENT = os.environ.get("MIN_TRADE_PERCENT", "2")
TV_WEBHOOK_SECRET = os.environ.get("TV_WEBHOOK_SECRET", "")

# Validate required variables
if not ORG_ID or not API_KEY or not PEM_CONTENT:
    raise RuntimeError("Missing required Coinbase environment variables.")

# --- Coinbase client ---
class CoinbaseClient:
    def __init__(self):
        self.org_id = ORG_ID
        self.api_key = API_KEY
        self.pem_content = PEM_CONTENT

    def _generate_jwt(self):
        """Generate JWT for Coinbase API"""
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode("utf-8"),
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            logger.error(f"JWT generation failed: {e}")
            return None

        payload = {
            "iss": self.org_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300  # 5 minutes expiry
        }

        token = jwt.encode(payload, private_key, algorithm="ES256")
        return token

    def request(self, method, url, **kwargs):
        """Make an authenticated request to Coinbase API"""
        jwt_token = self._generate_jwt()
        if not jwt_token:
            raise RuntimeError("Cannot make request without JWT")

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {jwt_token}"
        response = requests.request(method, url, headers=headers, **kwargs)
        return response

# --- Initialize client ---
client = CoinbaseClient()

# --- Test connection (optional) ---
def test_connection():
    try:
        # Example endpoint: get user accounts
        resp = client.request("GET", "https://api.coinbase.com/v2/accounts")
        if resp.status_code == 200:
            logger.success("✅ Coinbase connection successful")
            return True
        else:
            logger.error(f"Coinbase API error: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Coinbase connection failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()
