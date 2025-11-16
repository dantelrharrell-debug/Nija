# 1️⃣ Standard library & external imports
import os
import datetime
import jwt  # PyJWT library
import time
import requests

# 2️⃣ Verify environment variables
print("🔹 Verifying Coinbase env variables:")

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")  # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")        # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM block

print("COINBASE_ORG_ID:", COINBASE_ORG_ID)
print("COINBASE_API_KEY_ID (short UUID):", COINBASE_API_KEY_ID)
print("COINBASE_API_SUB (full path):", COINBASE_API_SUB)
print("COINBASE_PEM_CONTENT length:", len(COINBASE_PEM_CONTENT or ""))

# 3️⃣ Check for missing env vars
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
    raise SystemExit(f"❌ Missing env vars: {missing}")

# === Fix PEM line breaks if stored with literal \n ===
COINBASE_PEM_CONTENT = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()

# Check PEM formatting
pem_lines = COINBASE_PEM_CONTENT.split("\n")
if not COINBASE_PEM_CONTENT.startswith("-----BEGIN EC PRIVATE KEY-----") or not COINBASE_PEM_CONTENT.endswith("-----END EC PRIVATE KEY-----"):
    print("⚠️ Warning: PEM does not have correct BEGIN/END headers")

if any(len(line.strip()) == 0 for line in pem_lines[1:-1]):
    print("⚠️ Warning: Empty line inside PEM block (may cause load errors)")

# Check container UTC time
utc_now = datetime.datetime.utcnow()
print("Container UTC time:", utc_now.isoformat())

# Optional: Check Coinbase server time for drift
try:
    resp = requests.get("https://api.coinbase.com/v2/time", timeout=5)
    resp.raise_for_status()
    coinbase_time = datetime.datetime.strptime(resp.json()['data']['iso'], "%Y-%m-%dT%H:%M:%SZ")
    drift = abs((coinbase_time - utc_now).total_seconds())
    print("Coinbase UTC time:", coinbase_time.isoformat())
    print(f"Time drift: {drift} seconds")
    if drift > 30:
        print("⚠️ Warning: Significant time drift (>30s) detected. JWTs may fail!")
except Exception as e:
    print("⚠️ Could not check Coinbase server time:", e)

print("✅ Env variable verification complete. You can now generate JWT.")

# 4️⃣ JWT generation function
def generate_jwt(sub: str, pem: str, expiry_sec: int = 60):
    now_ts = int(time.time())
    payload = {
        "sub": sub,
        "iat": now_ts,
        "exp": now_ts + expiry_sec,
        "jti": f"test-{now_ts}"
    }
    try:
        token = jwt.encode(payload, pem, algorithm="ES256")
        print("✅ JWT generated successfully!")
        print("JWT preview (first 100 chars):", token[:100])
        decoded = jwt.decode(token, options={"verify_signature": False})
        print("Decoded JWT payload:", decoded)
        return token
    except Exception as e:
        print("❌ Failed to generate JWT:", e)
        return None

# 5️⃣ Dry-run JWT Test
jwt_token = generate_jwt(COINBASE_API_SUB, COINBASE_PEM_CONTENT)

# 6️⃣ Optional: test Coinbase API access
if jwt_token:
    try:
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=10)
        if response.status_code == 200:
            accounts = response.json().get("data", [])
            print(f"✅ Successfully fetched {len(accounts)} accounts from Coinbase.")
            for acc in accounts[:5]:  # preview first 5
                print(f"- {acc['id']}: {acc['balance']['amount']} {acc['balance']['currency']}")
        else:
            print(f"❌ Coinbase API call failed with status {response.status_code}: {response.text}")
    except Exception as e:
        print("❌ Failed to fetch Coinbase accounts:", e)

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
