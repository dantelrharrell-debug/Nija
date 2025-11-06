import os
import time
import hmac
import hashlib
import base64
import json
import requests
from loguru import logger

# -----------------------------
# 1️⃣ Load environment variables
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

# Safety check
if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    logger.error("❌ Missing Coinbase API credentials!")
    raise SystemExit(1)
logger.info("✅ Coinbase credentials detected.")


# -----------------------------
# 2️⃣ Helper: JWT generation
# -----------------------------
def generate_jwt():
    header = {"alg": "HS256", "typ": "JWT"}
    iat = int(time.time())
    exp = iat + 300  # JWT valid for 5 minutes
    payload = {"iat": iat, "exp": exp, "sub": API_KEY}

    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    message = f"{header_b64}.{payload_b64}"

    # If API_SECRET is PEM formatted, remove newlines and decode properly
    secret_bytes = API_SECRET.encode()

    signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")

    jwt_token = f"{message}.{signature_b64}"
    return jwt_token


# -----------------------------
# 3️⃣ Helper: Make authenticated request
# -----------------------------
def cdp_get(path):
    jwt_token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "CB-VERSION": "2025-11-05",
        "Content-Type": "application/json"
    }
    url = f"{API_BASE_URL}{path}"
    response = requests.get(url, headers=headers)
    if response.status_code == 401:
        logger.error("❌ Coinbase API Unauthorized (401). Check API key, secret, or endpoint.")
        logger.debug(f"Response: {response.text}")
        raise SystemExit(1)
    elif not response.ok:
        logger.error(f"❌ Coinbase API Error: {response.status_code}")
        logger.debug(f"Response: {response.text}")
        raise SystemExit(1)
    return response.json()


# -----------------------------
# 4️⃣ Test endpoint
# -----------------------------
if __name__ == "__main__":
    try:
        accounts = cdp_get("/platform/v2/accounts")
        logger.success("✅ Coinbase API test successful! Accounts data:")
        logger.info(accounts)
    except Exception as e:
        logger.error(f"❌ Failed to connect to Coinbase API: {e}")
