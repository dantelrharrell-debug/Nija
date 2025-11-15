# ./app/nija_client.py  (drop this file into your repo - overwrite existing)
import os
import sys
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Basic logging to container stdout (so Railway/Render logs show it)
logger.remove()
logger.add(lambda m: print(m, end=""))

# Constants
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200  # sanity check

def write_pem_from_env():
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.warning("COINBASE_PEM_CONTENT not set in environment. Skipping PEM write.")
        return None
    # If literal "\n" present, convert to actual newlines
    pem_text = pem_env.replace("\\n", "\n") if "\\n" in pem_env and "\n" not in pem_env else pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes)")
        if len(pem_text) < MIN_PEM_LENGTH:
            logger.warning("COINBASE_PEM_CONTENT looks very short (<200 bytes). This is likely truncated.")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception("Failed to write PEM file: " + str(e))
        return None

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}. Make sure you uploaded the full PEM.")
        sys.exit(1)
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file too short ({len(data)} bytes). Cannot generate JWT.")
        sys.exit(1)
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded successfully.")
        return key
    except Exception as e:
        logger.exception("Could not deserialize PEM private key: " + str(e))
        sys.exit(1)

def build_jwt(private_key, org_id, kid):
    now = int(time.time())
    payload = {"sub": org_id, "iat": now, "exp": now + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def verify_jwt_struct(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("JWT header (unverified): " + str(header))
        logger.info("JWT payload (unverified): " + str(payload))
        return header, payload
    except Exception as e:
        logger.exception("Failed to decode JWT locally: " + str(e))
        return None, None

def test_coinbase_accounts(token, endpoint="https://api.exchange.coinbase.com/accounts"):
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")}
    try:
        resp = requests.get(endpoint, headers=headers, timeout=12)
        logger.info(f"Coinbase response status: {resp.status_code}")
        logger.info("Coinbase response body (truncated):\n" + (resp.text[:2000] if resp.text else ""))
        return resp
    except Exception as e:
        logger.exception("Coinbase request failed: " + str(e))
        return None

def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")  # should be API key UUID only (no 'organizations/...')
    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH, ORG_ID, or KID; cannot proceed with JWT generation.")
        return

    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    logger.info("Generated JWT (preview): " + (token[:200] if token else ""))

    verify_jwt_struct(token)

    # Test Coinbase Advanced Trade API endpoint
    resp = test_coinbase_accounts(token, endpoint=os.environ.get("COINBASE_TEST_ENDPOINT", "https://api.exchange.coinbase.com/accounts"))
    if resp is None:
        logger.error("No response from Coinbase (exception).")
    elif resp.status_code == 401:
        logger.error("Coinbase returned 401 Unauthorized. Likely kid, sub, or time skew issue.")
    else:
        logger.info("Coinbase call succeeded or returned non-401 code.")

def get_coinbase_headers():
    pem_path = os.environ.get("COINBASE_PEM_PATH") or PEM_FILE_PATH
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")
    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    return {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")}

if __name__ == "__main__":
    startup_test()
