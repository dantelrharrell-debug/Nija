# /app/nija_client.py  (replace existing file with this)
import os
import sys
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda msg: print(msg, end=''))  # console logging

PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_BYTES = 200

def write_pem_from_env():
    s = os.environ.get("COINBASE_PEM_CONTENT")
    if not s:
        logger.info("COINBASE_PEM_CONTENT not set in environment.")
        return None
    # convert literal \n to real newlines if necessary
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    s = s.strip().strip('"').strip("'")
    if not s.endswith("\n"):
        s += "\n"
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(s)
        logger.info(f"WROTE PEM -> {PEM_FILE_PATH} ({len(s)} bytes)")
        if len(s) < MIN_PEM_BYTES:
            logger.warning("PEM looks short (<200 bytes) — likely truncated.")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception("Failed to write PEM file: " + str(e))
        return None

def load_private_key(path):
    if not os.path.exists(path):
        logger.error("PEM file not found at: " + str(path))
        raise SystemExit(1)
    data = open(path, "rb").read()
    logger.info(f"PEM file bytes: {len(data)}")
    if len(data) < MIN_PEM_BYTES:
        logger.warning("PEM file length suspiciously short.")
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("✅ Private key loaded. Key type: " + str(type(key)))
        return key
    except Exception as e:
        logger.exception("Failed to deserialize PEM private key: " + str(e))
        raise

def build_jwt(key, org_id, kid, offset_seconds=0):
    now = int(time.time()) + int(offset_seconds)
    payload = {"sub": org_id, "iat": now, "exp": now + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

def decode_unverified(token):
    try:
        hdr = jwt.get_unverified_header(token)
    except Exception as e:
        hdr = f"ERROR: {e}"
    try:
        pld = jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        pld = f"ERROR: {e}"
    return hdr, pld

def get_coinbase_date():
    try:
        r = requests.head("https://api.coinbase.com/v2/", timeout=8)
        return r.headers.get("Date"), r.status_code
    except Exception as e:
        logger.exception("Failed to fetch Coinbase server Date header: " + str(e))
        return None, None

def test_api(token, url="https://api.exchange.coinbase.com/accounts"):
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION","2025-01-01")}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        logger.info(f"API call {url} -> {r.status_code}")
        # print a truncated body (safe)
        logger.info("Response (truncated 2000 chars):\n" + (r.text[:2000] if r.text else ""))
        return r
    except Exception as e:
        logger.exception("API request failed: " + str(e))
        return None

def startup_test():
    logger.info("=== Startup diagnostic ===\n")
    # Show env vars (safe lengths only)
    logger.info("ENV COINBASE_ORG_ID present: " + str(bool(os.environ.get("COINBASE_ORG_ID"))))
    logger.info("ENV COINBASE_JWT_KID present: " + str(bool(os.environ.get("COINBASE_JWT_KID"))))
    logger.info("ENV COINBASE_PEM_CONTENT present: " + str(bool(os.environ.get("COINBASE_PEM_CONTENT"))))
    logger.info("ENV COINBASE_PEM_PATH present: " + str(bool(os.environ.get("COINBASE_PEM_PATH"))))

    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")

    logger.info(f"Using PEM_PATH: {pem_path}")
    logger.info(f"Using ORG_ID : {org_id}")
    logger.info(f"Using KID    : {kid}")

    # Compare local time vs Coinbase Date header
    cb_date, status = get_coinbase_date()
    local_utc = datetime.datetime.utcnow().isoformat()
    logger.info("Local UTC now: " + local_utc)
    logger.info("Coinbase Date header: " + str(cb_date) + " (status: " + str(status) + ")")

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH or ORG_ID or KID -> cannot proceed.")
        return

    # Load private key
    try:
        key = load_private_key(pem_path)
    except SystemExit:
        return
    except Exception:
        logger.error("Key load failed.")
        return

    # Try small offsets to handle clock skew: -5..+5 seconds (expandable)
    for offset in [-5, -2, -1, 0, 1, 2, 5]:
        logger.info(f"\n--- Trying offset {offset} seconds ---")
        try:
            token = build_jwt(key, org_id, kid, offset_seconds=offset)
        except Exception as e:
            logger.exception("JWT build failed: " + str(e))
            continue

        # Show unverified header/payload
        hdr, pld = decode_unverified(token)
        logger.info("JWT header (unverified): " + str(hdr))
        logger.info("JWT payload (unverified): " + str(pld))

        # Test against Coinbase exchange endpoint
        resp = test_api(token)
        if resp is None:
            logger.warning("No response object returned.")
            continue
        if resp.status_code == 200:
            logger.info("✅ SUCCESS with offset " + str(offset))
            break
        else:
            logger.warning("Not success (status " + str(resp.status_code) + "). Response body above.")

if __name__ == "__main__":
    startup_test()
