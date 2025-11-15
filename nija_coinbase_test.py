# nija_coinbase_test.py
import os, time, datetime, jwt, requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import sys

logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Config / environment
# -----------------------------
PEM_FILE_PATH = "/app/coinbase.pem"
MIN_PEM_LENGTH = 200

# Coinbase credentials (set these in your environment)
# COINBASE_PEM_CONTENT = full EC private key PEM (including BEGIN/END lines)
# COINBASE_ORG_ID     = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
# COINBASE_KEY_ID     = "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
# COINBASE_API_VERSION = "2025-01-01" (optional, default used)

def write_pem_from_env():
    s = os.environ.get("COINBASE_PEM_CONTENT")
    if not s:
        logger.error("COINBASE_PEM_CONTENT not found in environment.")
        sys.exit(1)
    s = s.replace("\\n","\n") if "\\n" in s and "\n" not in s else s
    s = s.strip().strip('"').strip("'")
    if not s.endswith("\n"):
        s += "\n"
    if len(s) < MIN_PEM_LENGTH:
        logger.warning(f"PEM content very short ({len(s)} bytes), likely truncated!")
    with open(PEM_FILE_PATH, "w", newline="\n") as f:
        f.write(s)
    logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(s)} bytes)")
    return PEM_FILE_PATH

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        sys.exit(1)
    data = open(path,"rb").read()
    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file too short ({len(data)} bytes)")
        sys.exit(1)
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded successfully")
        return key
    except Exception as e:
        logger.exception(f"Failed to deserialize PEM key: {e}")
        sys.exit(1)

def build_jwt(private_key, org_id, key_id, method="GET", path="/api/v3/brokerage/accounts"):
    """Build JWT exactly as Coinbase Advanced Trade API expects"""
    iat = int(time.time())
    exp = iat + 300  # 5 minutes
    sub = f"organizations/{org_id}/apiKeys/{key_id}"
    payload = {
        "sub": sub,
        "iat": iat,
        "exp": exp,
        "method": method,
        "path": path
    }
    headers = {"kid": key_id}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def test_coinbase(token):
    url = "https://api.coinbase.com/api/v3/brokerage/accounts"
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("COINBASE_API_VERSION","2025-01-01")
    }
    try:
        r = requests.get(url, headers=headers, timeout=12)
        logger.info(f"Coinbase response: {r.status_code}")
        logger.info("Response text (truncated 2000 chars):\n" + r.text[:2000])
        return r
    except Exception as e:
        logger.exception(f"Request failed: {e}")
        return None

def main():
    logger.info("=== Starting Coinbase JWT test ===")
    pem_path = write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    key_id = os.environ.get("COINBASE_KEY_ID")

    if not org_id or not key_id:
        logger.error("COINBASE_ORG_ID or COINBASE_KEY_ID missing in environment")
        sys.exit(1)

    private_key = load_private_key(pem_path)
    token = build_jwt(private_key, org_id, key_id)
    logger.info("JWT preview: " + token[:200])

    # Decode locally just to verify
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info(f"JWT header: {header}")
        logger.info(f"JWT payload: {payload}")
    except Exception as e:
        logger.warning(f"Failed to decode JWT locally: {e}")

    # Test request
    test_coinbase(token)

if __name__ == "__main__":
    main()
