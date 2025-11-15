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

logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# Where we will write PEM if using COINBASE_PEM_CONTENT env
DEFAULT_PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 200  # sanity check threshold

def write_pem_from_env(pem_path=DEFAULT_PEM_PATH):
    s = os.environ.get("COINBASE_PEM_CONTENT")
    if not s:
        logger.warning("COINBASE_PEM_CONTENT not set in environment. Skipping PEM write.")
        return None
    # convert literal \n into real newlines if needed
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    s = s.strip().strip('"').strip("'")
    if not s.endswith("\n"):
        s += "\n"
    try:
        with open(pem_path, "w", newline="\n") as f:
            f.write(s)
        logger.info(f"Wrote PEM to {pem_path} ({len(s)} bytes)")
        if len(s) < MIN_PEM_LENGTH:
            logger.warning(f"PEM looks short ({len(s)} bytes) — likely truncated")
        return pem_path
    except Exception as e:
        logger.exception(f"Failed to write PEM file: {e}")
        return None

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        raise FileNotFoundError(path)
    data = open(path, "rb").read()
    logger.info(f"PEM file size: {len(data)} bytes  (preview head: {data[:30]!r})")
    if len(data) < MIN_PEM_LENGTH:
        logger.warning("PEM file appears short; maybe truncated or wrong file.")
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        logger.info("✅ Private key loaded successfully.")
        return key
    except Exception as e:
        logger.exception("Failed to deserialize PEM private key: " + str(e))
        raise

def build_jwt(private_key, org_id, kid=None):
    now = int(time.time())
    payload = {"sub": org_id, "iat": now, "exp": now + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def debug_print_jwt(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        logger.info("JWT header (unverified): " + str(header))
        logger.info("JWT payload (unverified): " + str(payload))
    except Exception as e:
        logger.exception("Failed to decode JWT locally: " + str(e))

def test_endpoints(token):
    headers_api = {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01")}
    endpoints = [
        ("Coinbase API v2", "https://api.coinbase.com/v2/accounts", headers_api),
        ("Coinbase Exchange (Advanced Trade)", "https://api.exchange.coinbase.com/accounts", {"Authorization": f"Bearer {token}"})
    ]
    for name, url, headers in endpoints:
        try:
            logger.info(f"Calling {name} -> {url}")
            r = requests.get(url, headers=headers, timeout=12)
            logger.info(f"{name} status: {r.status_code}")
            logger.info(f"{name} body (truncated): {r.text[:2000]}")
        except Exception as e:
            logger.exception(f"Request to {url} failed: {e}")

def startup_test():
    logger.info("=== Nija Coinbase JWT startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")  # API Key ID (UUID only)

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat() + " (ISO) / unix: " + str(int(time.time())))

    if not pem_path or not org_id or not kid:
        logger.error("Missing required env: COINBASE_PEM_CONTENT/COINBASE_PEM_PATH or COINBASE_ORG_ID or COINBASE_JWT_KID.")
        return

    try:
        key = load_private_key(pem_path)
    except Exception:
        logger.error("Cannot load private key — aborting startup test.")
        return

    try:
        token = build_jwt(key, org_id, kid)
    except Exception as e:
        logger.exception("Failed to build JWT: " + str(e))
        return

    logger.info("Generated JWT preview (first 200 chars): " + (token[:200] if token else ""))
    debug_print_jwt(token)

    # explicit local time check: print iat/exp and server time
    try:
        payload_unverified = jwt.decode(token, options={"verify_signature": False})
        iat = payload_unverified.get("iat")
        exp = payload_unverified.get("exp")
        logger.info(f"Token iat: {iat}  exp: {exp}  now: {int(time.time())}  (diff now-iat = {int(time.time()) - iat})")
    except Exception:
        pass

    # test endpoints
    test_endpoints(token)

if __name__ == "__main__":
    startup_test()
