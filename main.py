# ✅ main.py
# 1️⃣ Standard library & external imports
import os
import time
import requests
import jwt
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.add(lambda msg: print(msg, end=''))  # container-friendly stdout

# 2️⃣ Verify environment variables
logger.info("🔹 Verifying Coinbase env variables...")

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")            # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")                  # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")          # private key PEM

logger.info(f"COINBASE_ORG_ID: {COINBASE_ORG_ID}")
logger.info(f"COINBASE_API_KEY_ID (short UUID): {COINBASE_API_KEY_ID}")
logger.info(f"COINBASE_API_SUB (full path): {COINBASE_API_SUB}")
logger.info(f"COINBASE_PEM_CONTENT length: {len(COINBASE_PEM_CONTENT or '')}")

missing = []
for name, val in [
    ("COINBASE_ORG_ID", COINBASE_ORG_ID),
    ("COINBASE_API_KEY_ID", COINBASE_API_KEY_ID),
    ("COINBASE_API_SUB", COINBASE_API_SUB),
    ("COINBASE_PEM_CONTENT", COINBASE_PEM_CONTENT)
]:
    if not val:
        missing.append(name)

if missing:
    logger.error(f"❌ Missing env vars: {missing}")
    raise SystemExit(1)

# 3️⃣ Fix PEM line breaks
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace("\r", "").strip().strip('"').strip("'")

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    logger.success("✅ PEM loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {e}")
    raise SystemExit(1)

# 4️⃣ JWT generator
def generate_jwt(sub: str, kid: str, request_path: str = "/", method: str = "GET", expiry_sec: int = 120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + expiry_sec,
        "sub": sub,
        "request_path": request_path,
        "method": method
    }
    headers_jwt = {"alg": "ES256", "kid": kid}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    return token

# 5️⃣ Test Coinbase API
def test_coinbase(sub: str, kid: str):
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    token = generate_jwt(sub, kid, request_path=path)
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-16"}
    try:
        r = requests.get(f"https://api.coinbase.com{path}", headers=headers, timeout=10)
        return r
    except Exception as e:
        logger.error(f"Request exception: {e}")
        return None

# 6️⃣ Auto-detect working sub/kid
subs_to_try = [
    COINBASE_API_SUB,       # full path (preferred)
    COINBASE_API_KEY_ID     # fallback short UUID
]

working_sub = None
for candidate_sub in subs_to_try:
    r = test_coinbase(candidate_sub, COINBASE_API_KEY_ID)
    if r and r.status_code == 200:
        working_sub = candidate_sub
        logger.success(f"✅ Working sub detected: {working_sub}")
        break
    else:
        status = r.status_code if r else "ERR"
        logger.warning(f"⚠️ Sub failed: {candidate_sub} -> {status}")
        if r and r.status_code == 401:
            logger.warning(f"⚠️ 401 Unauthorized (JWT rejected). Response: {r.text}")

if not working_sub:
    logger.error("❌ No valid sub found. Check API key, PEM, permissions.")
    raise SystemExit(1)

# 7️⃣ Safe GET / POST wrapper
def call_coinbase(path: str, method="GET", data=None, retries=3):
    for attempt in range(1, retries + 1):
        token = generate_jwt(working_sub, COINBASE_API_KEY_ID, request_path=path, method=method)
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

        if resp and resp.status_code in (200, 201):
            return resp.json()
        elif resp and resp.status_code == 401:
            logger.warning("⚠️ 401 Unauthorized (JWT rejected). Retrying with new JWT...")
            time.sleep(1)
            continue
        else:
            time.sleep(1)
            continue

    logger.error("All retries failed. Check API key, PEM, permissions, and clock.")
    return None

# 8️⃣ Fetch funded accounts
def fetch_funded_accounts():
    path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    accounts = call_coinbase(path, method="GET", retries=5)
    if not accounts:
        return None
    funded = [a for a in accounts if float(a.get("balance", {}).get("amount", 0) or 0) > 0]
    return funded

# 9️⃣ Main
def main():
    logger.info("Starting Nija Trading Bot (test connection)...")
    accounts = fetch_funded_accounts()
    if accounts is None:
        logger.error("Cannot fetch Coinbase accounts. Exiting.")
        return
    logger.success("✅ Accounts fetched:")
    for acc in accounts:
        logger.info(acc)

if __name__ == "__main__":
    main()
