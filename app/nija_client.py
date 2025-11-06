# nija_client.py
import os
import time
import jwt
import requests
from loguru import logger

# -----------------------------
# Load Coinbase CDP keys from environment
# -----------------------------
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "").replace("\\n", "\n")  # fix escaped newlines
CDP_API_KEY_PASSPHRASE = os.getenv("CDP_API_KEY_PASSPHRASE", "")  # optional
CDP_API_BASE = "https://api.cdp.coinbase.com"

# -----------------------------
# Preflight check for keys
# -----------------------------
if not all([CDP_API_KEY_ID, CDP_API_KEY_SECRET]):
    logger.error("Missing Coinbase CDP credentials. Set CDP_API_KEY_ID and CDP_API_KEY_SECRET in environment.")
    raise SystemExit(1)

logger.info("Coinbase CDP credentials detected.")

# -----------------------------
# JWT generator
# -----------------------------
def generate_jwt(request_method="GET", request_path="/platform/v2/accounts", request_body=""):
    iat = int(time.time())
    exp = iat + 120  # max 2 min lifetime
    payload = {
        "sub": CDP_API_KEY_ID,
        "iat": iat,
        "exp": exp,
        "requestMethod": request_method,
        "requestPath": request_path,
        "requestBody": request_body
    }

    try:
        token = jwt.encode(payload, CDP_API_KEY_SECRET, algorithm="ES256")
        return token
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        raise

# -----------------------------
# General Coinbase CDP request
# -----------------------------
def cdp_request(method="GET", path="/platform/v2/accounts", body=""):
    url = f"{CDP_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {generate_jwt(method, path, body)}",
        "CB-ACCESS-PASSPHRASE": CDP_API_KEY_PASSPHRASE,
        "Content-Type": "application/json"
    }

    response = requests.request(method, url, headers=headers, data=body)
    if response.status_code == 401:
        logger.error("❌ Coinbase API Unauthorized (401). Check keys & permissions.")
    elif response.status_code >= 400:
        logger.error(f"❌ Coinbase API Error {response.status_code}: {response.text}")
    else:
        logger.success(f"✅ Request successful: {response.status_code}")
    return response

# -----------------------------
# Example test block
# -----------------------------
if __name__ == "__main__":
    logger.info("Testing Coinbase CDP connection...")
    resp = cdp_request()
    try:
        print(resp.json())
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
