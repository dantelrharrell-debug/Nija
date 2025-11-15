import os
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.add(lambda msg: print(msg, end=''))  # basic console logging

# -------------------------------
# Load/write PEM
# -------------------------------
def write_pem_from_env():
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_content:
        raise ValueError("COINBASE_PEM_CONTENT not set")
    pem_path = "/app/coinbase.pem"
    with open(pem_path, "w", newline="\n") as f:
        f.write(pem_content.replace("\\n", "\n"))
    logger.info(f"PEM written to {pem_path}")
    return pem_path

def load_private_key(pem_path):
    with open(pem_path, "rb") as f:
        key_data = f.read()
    key = serialization.load_pem_private_key(key_data, password=None, backend=default_backend())
    logger.info("✅ PEM loaded successfully. Key type: " + str(type(key)))
    return key

# -------------------------------
# Build JWT (with optional time correction)
# -------------------------------
def build_jwt(key, org_id, kid, time_offset=0):
    now = int(time.time()) + int(time_offset)
    payload = {
        "sub": org_id,
        "iat": now,
        "exp": now + 300  # max 5 minutes
    }
    headers = {
        "kid": kid
    }
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# -------------------------------
# Verify JWT locally
# -------------------------------
def verify_jwt(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("✅ JWT structure is valid")
        logger.info("JWT header: " + str(header))
        logger.info("JWT payload: " + str(payload))
    except Exception as e:
        logger.exception("❌ JWT verification failed: " + str(e))
        return False
    return True

# -------------------------------
# Fetch Coinbase UTC time
# -------------------------------
def fetch_coinbase_time():
    try:
        resp = requests.get("https://api.exchange.coinbase.com/time", timeout=10)
        resp.raise_for_status()
        coinbase_time = resp.json().get("epoch")
        logger.info("Coinbase UTC epoch: " + str(coinbase_time))
        return coinbase_time
    except Exception as e:
        logger.exception("Failed to fetch Coinbase time: " + str(e))
        return None

# -------------------------------
# Full startup test
# -------------------------------
def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")  # API Key ID (UUID only!)

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH, ORG_ID, or KID; cannot proceed with JWT generation.")
        return

    # Load private key
    key = load_private_key(pem_path)

    # Check Coinbase time for offset
    coinbase_epoch = fetch_coinbase_time()
    server_epoch = int(time.time())
    time_offset = 0
    if coinbase_epoch:
        time_offset = coinbase_epoch - server_epoch
        if abs(time_offset) > 5:
            logger.warning(f"Time offset detected! Adjusting JWT by {time_offset} seconds.")

    # Build JWT with corrected time
    token = build_jwt(key, org_id, kid, time_offset)
    logger.info("Generated JWT (preview): " + token[:200])

    # Verify JWT locally
    if not verify_jwt(token):
        logger.error("JWT is invalid. Stop before sending request.")
        return

    # Test Coinbase Advanced Trade API
    try:
        resp = requests.get(
            "https://api.exchange.coinbase.com/accounts",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12
        )
        logger.info("Status code: " + str(resp.status_code))
        logger.info("Response body (truncated): " + resp.text[:2000])
    except Exception as e:
        logger.exception(f"Coinbase request failed: {e}")

# -------------------------------
# Run test
# -------------------------------
if __name__ == "__main__":
    startup_test()
