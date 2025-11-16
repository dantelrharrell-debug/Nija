import os
import time
import requests
import jwt
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.add(lambda msg: print(msg, end=''))  # container-friendly stdout

# ----------------------------
# Required env variables
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")            # uuid only
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")                 # full path
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB:
    logger.error("Missing required Coinbase env vars.")
    raise SystemExit(1)

# ----------------------------
# Load PEM
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

# ----------------------------
# Auto-detect working sub/kid
# ----------------------------
def create_jwt(sub, kid, request_path="/api/v3/brokerage/organizations/{org}/accounts", method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)

def test_coinbase(token):
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-16"}
    return requests.get(url, headers=headers, timeout=10)

subs_to_try = [
    COINBASE_API_KEY_ID,        # short UUID
    COINBASE_API_SUB            # full path
]

working_sub = None
for candidate_sub in subs_to_try:
    token = create_jwt(candidate_sub, COINBASE_API_KID)
    r = test_coinbase(token)
    if r.status_code == 200:
        working_sub = candidate_sub
        logger.success(f"✅ Working sub detected: {working_sub}")
        break
    else:
        logger.warning(f"⚠️ Sub failed: {candidate_sub} -> {r.status_code}")
        if r.status_code == 401:
            logger.warning(f"⚠️ 401 Unauthorized (JWT rejected). Response: {r.text}")

if not working_sub:
    logger.error("❌ No valid sub found. Check API key, PEM, permissions.")
    raise SystemExit(1)

sub = working_sub
kid = COINBASE_API_KID

logger.info(f"JWT sub: {sub}")
logger.info(f"JWT kid: {kid}")
logger.info(f"Container time: {datetime.datetime.utcnow().isoformat()} UTC")  # Optional clock check

# ----------------------------
# JWT generator
# ----------------------------
def generate_jwt(request_path, method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# ----------------------------
# Safe GET (with retries)
# ----------------------------
def call_coinbase(path, method="GET", data=None, retries=3):
    for attempt in range(1, retries + 1):
        token = generate_jwt(path, method=method)
        url = f"https://api.coinbase.com{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-16",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10) if method.upper() == "GET" else requests.post(url, headers=headers, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Request exception: {e}")
            resp = None

        status = resp.status_code if resp else "ERR"
        logger.info(f"[Attempt {attempt}] {method} {path} -> HTTP {status}")

        if resp is None:
            time.sleep(1)
            continue

        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 401:
            logger.warning("⚠️ 401 Unauthorized (JWT rejected). Retrying with new JWT...")
            logger.warning(f"Response: {resp.text}")
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

if __name__ == "__main__":
    main()
