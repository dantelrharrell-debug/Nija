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
    logger.error("Missing one or more required environment variables: COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID")
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

# --- Build request ---
path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"

def generate_jwt(offset_seconds=0):
    iat = int(time.time()) + offset_seconds
    payload = {
        "iat": iat,
        "exp": iat + 120,        # 2 minutes expiry
        "sub": API_KEY_ID,       # API key ID
        "request_path": path,    # must exactly match
        "method": "GET"
    }
    headers = {
        "alg": "ES256",
        "kid": API_KEY_ID
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

# --- Attempt request with small clock-skew adjustment ---
success = False
for offset in [0, -5, 5]:  # try current time, 5s behind, 5s ahead
    try:
        token = generate_jwt(offset_seconds=offset)

        # Debug info
        print(f"Using time offset: {offset} seconds")
        print("JWT:", token)
        print("JWT Header:", jwt.get_unverified_header(token))
        print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
        print("Request path:", path)
        print("Request URL:", url)

        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-12"
        })

        print("HTTP status code:", resp.status_code)
        print("Response text:", resp.text)

        if resp.status_code == 200:
            success = True
            print("✅ Successfully fetched accounts!")
            break
        else:
            print("❌ Failed with status code:", resp.status_code)

    except Exception as e:
        logger.exception("Request failed: %s", e)

if not success:
    logger.error("All JWT attempts failed. Check API key, permissions, and server time.")
