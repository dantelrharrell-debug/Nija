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
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0")

# --- Load / decode PEM ---
PEM_CONTENT = None

# 1️⃣ Use literal PEM if present
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")
if PEM_RAW:
    PEM_CONTENT = PEM_RAW.replace("\\n", "\n")  # fix escaped newlines

# 2️⃣ Else decode base64 PEM if present
elif os.environ.get("COINBASE_PEM_B64", ""):
    try:
        pem_bytes = base64.b64decode(os.environ["COINBASE_PEM_B64"])
        PEM_CONTENT = pem_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to decode COINBASE_PEM_B64: {e}")

# 3️⃣ Validate
if not ORG_ID:
    raise RuntimeError("COINBASE_ORG_ID is missing")
if not API_KEY:
    raise RuntimeError("COINBASE_API_KEY is missing")
if not PEM_CONTENT:
    raise RuntimeError("No PEM available (COINBASE_PEM_CONTENT or COINBASE_PEM_B64 required)")

logger.info(f"Loaded PEM length: {len(PEM_CONTENT)}")
logger.info(f"LIVE_TRADING={LIVE_TRADING}")

# --- Normalize API_KEY path ---
if "organizations/" in API_KEY:
    API_KEY_PATH = API_KEY
else:
    API_KEY_PATH = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

logger.info(f"Using API_KEY_PATH: {API_KEY_PATH}")

# --- Coinbase client ---
class CoinbaseClient:
    def __init__(self):
        self.org_id = ORG_ID
        self.api_key = API_KEY_PATH
        self.pem_content = PEM_CONTENT

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
            "exp": int(time.time()) + 300  # 5 min
        }

        token = jwt.encode(payload, private_key, algorithm="ES256")
        return token

    def request(self, method, url, **kwargs):
        jwt_token = self._generate_jwt()
        if not jwt_token:
            raise RuntimeError("Cannot make request without JWT")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {jwt_token}"
        return requests.request(method, url, headers=headers, **kwargs)

# --- Initialize client ---
client = CoinbaseClient()

# --- Optional test function ---
def test_accounts():
    try:
        resp = client.request("GET", "https://api.coinbase.com/v2/accounts")
        if resp.status_code == 200:
            logger.success("✅ Coinbase accounts fetched successfully")
        else:
            logger.error(f"Failed to fetch accounts: {resp.status_code} {resp.text}")
        return resp
    except Exception as e:
        logger.error(f"Error fetching accounts: {type(e).__name__}: {e}")
        return None

if __name__ == "__main__":
    test_accounts()
