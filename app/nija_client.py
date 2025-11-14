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

# --- Load env vars ---
BOT_SECRET_KEY = os.environ.get("BOT_SECRET_KEY")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_B64 = os.environ.get("COINBASE_PEM_B64")
LIVE_TRADING = int(os.environ.get("LIVE_TRADING", 0))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MAX_TRADE_PERCENT = float(os.environ.get("MAX_TRADE_PERCENT", 10))
MIN_TRADE_PERCENT = float(os.environ.get("MIN_TRADE_PERCENT", 2))

# Optional
TV_WEBHOOK_SECRET = os.environ.get("TV_WEBHOOK_SECRET")

# --- Validate required env vars ---
if not BOT_SECRET_KEY:
    raise RuntimeError("BOT_SECRET_KEY missing")
if not COINBASE_ORG_ID:
    raise RuntimeError("COINBASE_ORG_ID missing")
if not COINBASE_API_KEY:
    raise RuntimeError("COINBASE_API_KEY missing")
if not COINBASE_PEM_B64:
    raise RuntimeError("COINBASE_PEM_B64 missing")

# --- Decode PEM ---
try:
    pem_bytes = base64.b64decode(COINBASE_PEM_B64)
    COINBASE_PEM_CONTENT = pem_bytes.decode("utf-8")
except Exception as e:
    raise RuntimeError(f"Failed to decode COINBASE_PEM_B64: {e}")

os.environ["COINBASE_PEM_CONTENT"] = COINBASE_PEM_CONTENT

# --- Coinbase Client ---
class CoinbaseClient:
    def __init__(self):
        self.org_id = COINBASE_ORG_ID
        self.api_key = COINBASE_API_KEY
        self.pem_content = COINBASE_PEM_CONTENT

    def _generate_jwt(self):
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
            "exp": int(time.time()) + 300  # 5 min expiry
        }

        token = jwt.encode(payload, private_key, algorithm="ES256")
        return token

    def request(self, method, url, **kwargs):
        jwt_token = self._generate_jwt()
        if not jwt_token:
            raise RuntimeError("Cannot make request without JWT")

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {jwt_token}"
        response = requests.request(method, url, headers=headers, **kwargs)
        return response

# --- Initialize client ---
client = CoinbaseClient()

# --- Test connection ---
def test_accounts():
    try:
        # Example endpoint, adjust to actual Coinbase endpoint if SDK is not used
        url = "https://api.coinbase.com/v2/accounts"
        resp = client.request("GET", url)
        if resp.status_code == 200:
            logger.success("✅ Coinbase API connected successfully!")
            return True
        else:
            logger.error(f"Coinbase API returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Coinbase API test failed: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    if test_accounts():
        logger.info("AUTH OK — bot ready to trade (check LIVE_TRADING).")
    else:
        logger.info("AUTH FAILED — fix env keys / PEM and redeploy.")
