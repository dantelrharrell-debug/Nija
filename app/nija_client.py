# ./app/nija_client.py
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
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# --- Config / paths ---
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_BYTES = 200
CB_API_VERSION = os.environ.get("CB_API_VERSION", "2025-01-01")

def write_pem_from_env():
    s = os.environ.get("COINBASE_PEM_CONTENT")
    if not s:
        logger.warning("COINBASE_PEM_CONTENT not set in environment. Skipping PEM write.")
        return None
    # Convert literal "\n" into newlines if necessary
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    s = s.strip().strip('"').strip("'")
    if not s.endswith("\n"):
        s += "\n"
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(s)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(s)} bytes)")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception("Failed to write PEM file: " + str(e))
        return None

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        raise FileNotFoundError(path)
    data = open(path, "rb").read()
    if len(data) < MIN_PEM_BYTES:
        logger.warning(f"PEM file is small ({len(data)} bytes). It may be truncated.")
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("Private key loaded OK.")
        return key
    except Exception as e:
        logger.exception("Could not deserialize PEM private key: " + str(e))
        raise

def normalize_kid(maybe_kid):
    """If user put full path (organizations/.../apiKeys/<uuid>), extract the uuid."""
    if not maybe_kid:
        return None
    if "/" in maybe_kid:
        uuid = maybe_kid.split("/")[-1]
        logger.info(f"COINBASE_JWT_KID appears to be a path; using last segment as kid: {uuid}")
        return uuid
    return maybe_kid

def build_jwt(private_key, org_id, kid):
    now = int(time.time())
    payload = {"sub": org_id, "iat": now, "exp": now + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def verify_jwt_structure(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("JWT header (unverified): " + str(header))
        logger.info("JWT payload (unverified): " + str(payload))
        return header, payload
    except Exception as e:
        logger.exception("Failed to decode JWT locally: " + str(e))
        return None, None

def call_endpoints(token):
    headers_v2 = {"Authorization": f"Bearer {token}", "CB-VERSION": CB_API_VERSION}
    headers_exchange = {"Authorization": f"Bearer {token}", "CB-VERSION": CB_API_VERSION}
    # Try Coinbase REST (v2) and Advanced Exchange endpoints (both show 401 differently sometimes)
    urls = [
        ("v2_accounts", "https://api.coinbase.com/v2/accounts", headers_v2),
        ("exchange_accounts", "https://api.exchange.coinbase.com/accounts", headers_exchange),
    ]
    for name, url, h in urls:
        try:
            resp = requests.get(url, headers=h, timeout=12)
            logger.info(f"[{name}] {url} -> status {resp.status_code}")
            logger.info(f"[{name}] body (truncated): {resp.text[:2000]}")
        except Exception as e:
            logger.exception(f"[{name}] request failed: {e}")

def check_time_skew(payload):
    now = int(time.time())
    iat = payload.get("iat")
    exp = payload.get("exp")
    if iat:
        diff = now - int(iat)
        logger.info(f"Now: {now}  iat: {iat}  exp: {exp}  (now - iat = {diff} seconds)")
        if abs(diff) > 60:
            logger.warning("Time skew detected: server time and token iat differ by > 60s. Coinbase may reject the token.")
    else:
        logger.warning("iat not present in payload to check time skew.")

def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    # write PEM if content env was set
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    logger.info(f"PEM_PATH: {pem_path}")
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid_env = os.environ.get("COINBASE_JWT_KID") or os.environ.get("COINBASE_API_KEY")
    kid = normalize_kid(kid_env)
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid} (from env: {kid_env})")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id or not kid:
        logger.error("Missing PEM_PATH or ORG_ID or KID. Please set COINBASE_PEM_CONTENT/COINBASE_PEM_PATH, COINBASE_ORG_ID, and COINBASE_JWT_KID (UUID).")
        return

    try:
        key = load_private_key(pem_path)
    except Exception:
        logger.error("Private key load failed; aborting startup test.")
        return

    token = build_jwt(key, org_id, kid)
    preview = token if len(token) < 500 else token[:200] + "..."
    logger.info("Generated JWT preview: " + preview)

    header, payload = verify_jwt_structure(token)  # prints header/payload
    if payload:
        check_time_skew(payload)

    # call both endpoints
    call_endpoints(token)

if __name__ == "__main__":
    startup_test()
