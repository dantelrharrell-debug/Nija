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

# --- Decode base64 PEM and set COINBASE_PEM_CONTENT ---
pem_b64 = os.environ.get("COINBASE_PEM_B64", "")
if not pem_b64:
    raise RuntimeError("COINBASE_PEM_B64 missing")

try:
    pem_bytes = base64.b64decode(pem_b64)
    PEM_CONTENT = pem_bytes.decode("utf-8")
except Exception as e:
    raise RuntimeError(f"Failed to decode COINBASE_PEM_B64: {e}")

# Set environment variable for backward compatibility
os.environ["COINBASE_PEM_CONTENT"] = PEM_CONTENT

# --- Load other env vars ---
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
LIVE_TRADING = int(os.environ.get("LIVE_TRADING", "0"))
BOT_SECRET_KEY = os.environ.get("BOT_SECRET_KEY", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MAX_TRADE_PERCENT = float(os.environ.get("MAX_TRADE_PERCENT", "10"))
MIN_TRADE_PERCENT = float(os.environ.get("MIN_TRADE_PERCENT", "2"))
TV_WEBHOOK_SECRET = os.environ.get("TV_WEBHOOK_SECRET", "")

if not ORG_ID or not API_KEY:
    raise RuntimeError("COINBASE_ORG_ID or COINBASE_API_KEY missing")

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
        """Example API call using JWT auth"""
        jwt_token = self._generate_jwt()
        if not jwt_token:
            raise RuntimeError("Cannot make request without JWT")

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {jwt_token}"
        response = requests.request(method, url, headers=headers, **kwargs)
        return response

# --- Initialize client ---
client = CoinbaseClient()

# --- Test function ---
def test_accounts():
    try:
        resp = client.request("GET", "https://api.coinbase.com/v2/accounts")
        data = resp.json()
        logger.success("✅ Coinbase accounts fetched (preview):")
        for a in data.get("data", [])[:5]:
            logger.info(f"- {a.get('id')}  balance={a.get('balance')}  name={a.get('name')}")
        return True
    except Exception as e:
        logger.error(f"Coinbase API test failed: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    ok = test_accounts()
    if ok:
        logger.info(f"AUTH OK — LIVE_TRADING={LIVE_TRADING}")
    else:
        logger.info("AUTH FAILED — check COINBASE keys and PEM")
