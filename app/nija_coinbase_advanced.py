# nija_coinbase_advanced.py
# Drop-in Advanced Coinbase client (JWT/PEM auth)

import os
import time
import logging
import requests

logger = logging.getLogger("nija_coinbase_advanced")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s:%(lineno)d - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)

BASE_URL = os.getenv("BASE_URL", "https://api.coinbase.com").rstrip("/")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", None)          # full PEM text
PEM_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH", None)        # optional PEM file path
KEY_ID = os.getenv("COINBASE_KEY_ID", None)                    # kid / API key id
ISS = os.getenv("COINBASE_ISS", None)                          # org issuer
JWT_EXP_SECONDS = int(os.getenv("COINBASE_JWT_EXP_SECONDS", "120"))

# Try pyjwt
try:
    import jwt as pyjwt
    HAS_PYJWT = True
except Exception:
    HAS_PYJWT = False
    logger.error("pyjwt not installed. Install with `pip install pyjwt`.")
    raise

def _load_pem():
    if PEM_CONTENT:
        return PEM_CONTENT
    if PEM_PATH and os.path.exists(PEM_PATH):
        with open(PEM_PATH, "r") as f:
            return f.read()
    raise RuntimeError("No PEM content found")

def _format_jwt_uri(method: str, path: str) -> str:
    method = method.upper()
    if not path.startswith("/"):
        path = "/" + path
    host = BASE_URL.replace("https://", "").replace("http://", "").rstrip("/")
    return f"{method} {host}{path}"

def build_jwt_token(method: str, path: str) -> str:
    pem = _load_pem()
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + JWT_EXP_SECONDS
    }
    if ISS:
        payload["iss"] = ISS

    headers = {"kid": KEY_ID, "alg": "ES256"}
    token = pyjwt.encode(payload, pem, algorithm="ES256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def debug_request(method: str, path: str, params=None, json_body=None, timeout=15):
    method = method.upper()
    if not path.startswith("/"):
        path = "/" + path
    full_url = BASE_URL + path
    headers = {"Content-Type": "application/json"}

    try:
        jwt_token = build_jwt_token(method, path)
        headers["Authorization"] = f"Bearer {jwt_token}"
    except Exception as e:
        logger.exception(f"Failed to build JWT: {e}")
        raise

    try:
        resp = requests.request(method, full_url, headers=headers, params=params, json=json_body, timeout=timeout)
        logger.debug(f"{method} {full_url} -> {resp.status_code}")
        return resp
    except Exception as e:
        logger.exception(f"HTTP request failed: {e}")
        raise

# Convenience endpoints
def get_accounts():
    return debug_request("GET", "/api/v3/brokerage/accounts")

def get_key_permissions():
    return debug_request("GET", "/api/v3/brokerage/key_permissions")
