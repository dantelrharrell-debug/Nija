# app/nija_client.py
import os
import sys
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Logging
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# PEM Configuration
# -----------------------------
PEM_FILE_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
MIN_PEM_LENGTH = 300  # Coinbase PEMs are usually 300+ bytes
BASE_URL = "https://api.cdp.coinbase.com"  # Coinbase Trade API base

# -----------------------------
# Helper Functions
# -----------------------------
def write_pem_from_env():
    """Write PEM from environment variable COINBASE_PEM_CONTENT"""
    pem_env = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_env:
        logger.error("COINBASE_PEM_CONTENT not set in environment.")
        sys.exit(1)
    pem_text = pem_env.replace("\\n", "\n") if "\\n" in pem_env and "\n" not in pem_env else pem_env
    pem_text = pem_text.strip().strip('"').strip("'")
    if not pem_text.endswith("\n"):
        pem_text += "\n"
    if len(pem_text) < MIN_PEM_LENGTH:
        logger.error(f"COINBASE_PEM_CONTENT too short ({len(pem_text)} bytes).")
        sys.exit(1)
    try:
        with open(PEM_FILE_PATH, "w", newline="\n") as f:
            f.write(pem_text)
        logger.info(f"Wrote PEM to {PEM_FILE_PATH} ({len(pem_text)} bytes).")
        return PEM_FILE_PATH
    except Exception as e:
        logger.exception(f"Failed to write PEM file: {e}")
        sys.exit(1)

def load_private_key(path):
    if not os.path.exists(path):
        logger.error(f"PEM file not found at {path}")
        sys.exit(1)
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < MIN_PEM_LENGTH:
        logger.error(f"PEM file too short ({len(data)} bytes). Cannot generate JWT.")
        sys.exit(1)
    try:
        key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
        return key
    except Exception as e:
        logger.exception(f"Failed to deserialize PEM private key: {e}")
        sys.exit(1)

def build_jwt(private_key, org_id, kid=None):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def get_coinbase_headers():
    pem_path = os.environ.get("COINBASE_PEM_PATH") or PEM_FILE_PATH
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")
    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    return {"Authorization": f"Bearer {token}", "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01"),
            "Content-Type": "application/json"}

def api_request(method, endpoint, data=None, params=None):
    """Send authenticated request to Coinbase Trade API"""
    url = BASE_URL + endpoint
    headers = get_coinbase_headers()
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=12)
        else:
            resp = requests.post(url, headers=headers, json=data, timeout=12)
        if not resp.ok:
            logger.warning(f"API {method} {endpoint} returned {resp.status_code}: {resp.text[:300]}")
        return resp
    except Exception as e:
        logger.exception(f"Request to {url} failed: {e}")
        return None

# -----------------------------
# Prebuilt Trading Actions
# -----------------------------
def get_accounts():
    return api_request("GET", "/v2/accounts")

def get_orders():
    return api_request("GET", "/v2/orders")

def place_order(product_id, side, order_type, size, price=None):
    data = {
        "product_id": product_id,
        "side": side,
        "type": order_type,
        "size": str(size),
    }
    if price:
        data["price"] = str(price)
    return api_request("POST", "/v2/orders", data=data)

def cancel_order(order_id):
    return api_request("POST", f"/v2/orders/{order_id}/cancel")

# -----------------------------
# Startup Test
# -----------------------------
def startup_test():
    logger.info("=== Nija Coinbase Trade API startup test ===")
    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")

    logger.info(f"PEM_PATH: {pem_path}")
    logger.info(f"ORG_ID : {org_id}")
    logger.info(f"KID    : {kid}")
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

    if not pem_path or not org_id:
        logger.error("Missing PEM_PATH or ORG_ID; cannot proceed with JWT generation.")
        sys.exit(1)

    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)
    resp = get_accounts()
    if resp is None:
        logger.error("Failed to fetch accounts.")
    else:
        logger.info(f"Accounts response: {resp.status_code}, {resp.text[:1000]}")

if __name__ == "__main__":
    startup_test()
