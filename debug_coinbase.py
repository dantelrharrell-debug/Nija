import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load environment variables ---
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not API_KEY_ID or not PEM or not ORG_ID:
    logger.error("Missing required environment variables: COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID")
    exit(1)

# --- Load private key ---
try:
    private_key = serialization.load_pem_private_key(
        PEM.encode(), password=None, backend=default_backend()
    )
    logger.info("Private key loaded successfully")
except Exception as e:
    logger.exception("Failed to load private key: %s", e)
    exit(1)

# --- Check Coinbase server time ---
try:
    server_time_resp = requests.get("https://api.coinbase.com/v2/time")
    server_time_resp.raise_for_status()
    coinbase_time = server_time_resp.json()["data"]["epoch"]
    logger.info(f"Coinbase server time: {coinbase_time}")
except Exception as e:
    logger.exception("Failed to fetch Coinbase server time: %s", e)
    exit(1)

# --- Build request ---
path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"

iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,        # 2 minutes expiry
    "sub": API_KEY_ID,       # API key ID
    "request_path": path,    # must match request
    "method": "GET"
}

# --- Generate JWT ---
try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"alg":"ES256","kid":API_KEY_ID})
    logger.info("JWT generated successfully")
except Exception as e:
    logger.exception("Failed to generate JWT: %s", e)
    exit(1)

# --- Debug output ---
print("\n--- JWT DEBUG INFO ---")
print("JWT:", token)
print("JWT Header:", jwt.get_unverified_header(token))
print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
print("Request path:", path)
print("Request URL:", url)
print("Local iat:", iat, "| Coinbase server time:", coinbase_time)
print("----------------------\n")

# --- Make request ---
try:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12"
    })
    print("HTTP status code:", resp.status_code)
    print("Response text:", resp.text)
    resp.raise_for_status()
except requests.exceptions.HTTPError as e:
    logger.error(f"Request failed: {e}")
except Exception as e:
    logger.exception("Unexpected error during request: %s", e)
