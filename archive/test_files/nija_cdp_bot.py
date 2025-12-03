import os
import time
import jwt
import requests
from loguru import logger

# -----------------------------
# Paste your keys here (or set in environment)
# -----------------------------
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID", "YOUR_KEY_ID_HERE")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "YOUR_PRIVATE_KEY_HERE").replace("\\n", "\n")
CDP_API_KEY_PASSPHRASE = os.getenv("CDP_API_KEY_PASSPHRASE", "")
CDP_API_BASE = os.getenv("CDP_API_BASE", "https://api.cdp.coinbase.com")

# -----------------------------
# Check keys
# -----------------------------
if not CDP_API_KEY_ID or not CDP_API_KEY_SECRET:
    logger.error("❌ Missing Coinbase CDP credentials! Fill in your keys.")
    raise SystemExit(1)

logger.info("✅ Coinbase CDP credentials detected.")

# -----------------------------
# Generate JWT
# -----------------------------
def generate_jwt(method="GET", path="/platform/v2/accounts", body=""):
    iat = int(time.time())
    exp = iat + 120
    payload = {
        "sub": CDP_API_KEY_ID,
        "iat": iat,
        "exp": exp,
        "requestMethod": method,
        "requestPath": path,
        "requestBody": body
    }
    try:
        return jwt.encode(payload, CDP_API_KEY_SECRET, algorithm="ES256")
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        raise

# -----------------------------
# Make request
# -----------------------------
def cdp_request(method="GET", path="/platform/v2/accounts", body=""):
    url = f"{CDP_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {generate_jwt(method, path, body)}",
        "CB-ACCESS-PASSPHRASE": CDP_API_KEY_PASSPHRASE,
        "Content-Type": "application/json"
    }
    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=10)
    except Exception as e:
        logger.error(f"HTTP request failed: {e}")
        raise

    if response.status_code == 401:
        logger.error("❌ Unauthorized! Check your CDP API key and PEM.")
        raise SystemExit(1)
    elif response.status_code >= 400:
        logger.error(f"❌ API Error {response.status_code}: {response.text}")
        raise SystemExit(1)
    else:
        logger.success(f"✅ API request successful: {response.status_code}")
        return response

# -----------------------------
# Test connection
# -----------------------------
if __name__ == "__main__":
    logger.info("Testing Coinbase CDP connection...")
    resp = cdp_request()
    try:
        data = resp.json()
        logger.info(f"Accounts data retrieved: {len(data)} items")
        print(data)
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
