# main.py
import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.add(lambda msg: print(msg, end=''))  # container-friendly stdout

# ----------------------------
# Required env variables (set these in Railway / container env)
# ----------------------------
# COINBASE_ORG_ID          = ce77e4ea-ecca-...
# COINBASE_API_KEY_ID      = 9e33d60c-c9d7-...   (UUID only)
# COINBASE_API_SUB         = organizations/<org_id>/apiKeys/<api_key_id>  (FULL path)
# COINBASE_API_KID         = same as COINBASE_API_SUB (recommended)
# COINBASE_PEM_CONTENT     = the raw PEM text (full block) OR set COINBASE_PEM_PATH
# COINBASE_PEM_PATH        = optional path to PEM file inside container

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")            # uuid only
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")                 # full path (recommended)
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB:
    logger.error("Missing required Coinbase env vars. See README in message.")
    raise SystemExit(1)

# ----------------------------
# Load PEM (prefer content then path)
# ----------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace("\r", "").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        logger.error(f"PEM path not found: {COINBASE_PEM_PATH}")
        raise SystemExit(1)
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace("\r", "").strip()
else:
    logger.error("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH.")
    raise SystemExit(1)

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {e}")
    raise SystemExit(1)

sub = COINBASE_API_KEY_ID         # sub MUST be the short UUID (API key id)
kid = COINBASE_API_KID           # kid header SHOULD be the FULL path organizations/.../apiKeys/...

logger.info(f"JWT sub: {sub}")
logger.info(f"JWT kid: {kid}")

# ----------------------------
# JWT generator
# ----------------------------
def generate_jwt(request_path, method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,  # short-lived
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Safe GET (with logging and simple retries)
# ----------------------------
def call_coinbase(path, method="GET", data=None, retries=3):
    for attempt in range(1, retries + 1):
        token = generate_jwt(path, method=method)
        url = f"https://api.coinbase.com{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-16",           # use today's date / API version
            "Content-Type": "application/json"
        }
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            else:
                resp = requests.post(url, headers=headers, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Request exception: {e}")
            resp = None

        status = resp.status_code if resp is not None else "ERR"
        logger.info(f"[Attempt {attempt}] {method} {path} -> HTTP {status}")

        if resp is None:
            time.sleep(1)
            continue

        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 401:
            logger.warning("⚠️ 401 Unauthorized (JWT rejected).")
            # short delay then retry (new JWT each attempt)
            time.sleep(1)
            continue
        else:
            logger.error(f"Request failed: {resp.status_code} {resp.text}")
            break

    logger.error("All retries failed. Check API key, PEM, permissions, and clock.")
    return None

# ----------------------------
# Fetch funded accounts
# ----------------------------
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    accounts = call_coinbase(path, method="GET", retries=5)
    if not accounts:
        return None
    # Coinbase returns list of accounts. Filter balances > 0
    funded = [a for a in accounts if float(a.get("balance", {}).get("amount", 0) or 0) > 0]
    return funded

def main():
    logger.info("Starting Nija Trading Bot (test connection)...")
    accounts = fetch_funded_accounts()
    if accounts is None:
        logger.error("Cannot fetch Coinbase accounts. Exiting.")
        return
    logger.success("✅ Accounts fetched:")
    logger.info(accounts)

if __name__ == "__main__":
    main()
