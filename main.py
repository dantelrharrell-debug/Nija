# main.py
import os
import datetime
import logging
from loguru import logger
from app.nija_client import CoinbaseClient
from app.start_bot_main import start_bot_main

# -----------------------------
# Environment / Credentials
# -----------------------------
api_key = os.getenv("COINBASE_API_KEY")
org_id = os.getenv("COINBASE_ORG_ID")
pem = os.getenv("COINBASE_PEM_CONTENT")
kid = os.getenv("COINBASE_KID")  # must be a string Key ID from Coinbase

if not all([api_key, org_id, pem, kid]):
    raise ValueError("Missing one or more Coinbase credentials: API_KEY, ORG_ID, PEM, KID")

logger.info("Starting Nija bot...")

# -----------------------------
# Helper to decode JWT for logging
# -----------------------------
def verify_jwt_struct(token):
    import base64, json
    h_b64, p_b64, _ = token.split(".")
    # pad base64
    def b64fix(s):
        return s + "=" * ((4 - len(s) % 4) % 4)
    header = json.loads(base64.urlsafe_b64decode(b64fix(h_b64)))
    payload = json.loads(base64.urlsafe_b64decode(b64fix(p_b64)))
    return header, payload

# -----------------------------
# Initialize CoinbaseClient
# -----------------------------
try:
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid)
    logger.info("CoinbaseClient initialized")

    # Build JWT and log its contents
    token = client._build_jwt()  # Ensure _build_jwt exists
    try:
        header, payload = verify_jwt_struct(token)
        logger.info(f"_build_jwt: JWT header.kid: {header.get('kid')}")
        logger.info(f"_build_jwt: JWT payload.sub: {payload.get('sub')}")
        logger.info(f"_build_jwt: Server UTC time: {datetime.datetime.utcnow().isoformat()}")
    except Exception as e:
        logger.exception("Failed to decode/log JWT contents: {}", e)

except Exception as e:
    logger.exception("Failed to init CoinbaseClient")
    raise e

# -----------------------------
# Test Coinbase API
# -----------------------------
try:
    status, resp = client.request_auto("GET", "/v2/accounts")
    logger.info(f"Coinbase API test status: {status}")
    if status != 200:
        logger.warning(f"Coinbase API response: {resp}")
except Exception as e:
    logger.exception("Coinbase API test failed")
    raise e

# -----------------------------
# Start Bot Main Loop
# -----------------------------
try:
    start_bot_main(client)
except Exception as e:
    logger.exception("Failed to start bot main")
    raise e
