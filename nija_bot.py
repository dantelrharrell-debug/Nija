import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

# ----------------------------
# Container-friendly logging
# ----------------------------
logger.add(lambda msg: print(msg, end=''))

# ----------------------------
# Load environment variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not COINBASE_API_SUB:
    raise SystemExit("❌ Missing COINBASE_ORG_ID or COINBASE_API_SUB in env")

# ----------------------------
# Load PEM safely
# ----------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace('\r', '').strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace('\r', '').strip()
else:
    raise SystemExit("❌ No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

sub = COINBASE_API_SUB
kid = COINBASE_API_KID
logger.info(f"JWT sub: {sub}")
logger.info(f"JWT kid: {kid}")

# ----------------------------
# JWT generator
# ----------------------------
def generate_jwt(path):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,  # JWT valid for 2 minutes
        "sub": sub,
        "request_path": path,
        "method": "GET"
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Safe request with retries
# ----------------------------
def safe_get(path, max_retries=3):
    for attempt in range(1, max_retries + 1):
        token = generate_jwt(path)
        url = f"https://api.coinbase.com{path}"
        headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"}

        resp = requests.get(url, headers=headers)
        logger.info(f"[Attempt {attempt}] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            logger.success("✅ Request successful")
            return resp.json()
        elif resp.status_code == 401:
            logger.warning("⚠️ 401 Unauthorized. Regenerating JWT...")
            time.sleep(1)
        else:
            logger.error(f"⚠️ Request failed: {resp.text}")
            break
    logger.error("❌ All retries failed. Check API key, PEM, permissions, or clock.")
    return None

# ----------------------------
# Fetch funded accounts
# ----------------------------
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    return safe_get(path)

# ----------------------------
# Main bot logic
# ----------------------------
def main():
    logger.info("Starting Nija Trading Bot...")
    accounts = fetch_funded_accounts()
    if not accounts:
        logger.error("Cannot fetch Coinbase accounts. Stopping bot to prevent crash loop.")
        return

    logger.info("Bot is ready to trade!")
    logger.info(accounts)
    # Place your trading logic here

if __name__ == "__main__":
    main()
