import os
import time
import datetime
import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -------------------------------
# Logging helper
# -------------------------------
def log(msg):
    print(f"[{datetime.datetime.utcnow().isoformat()}] {msg}")

# -------------------------------
# Load/write PEM from env
# -------------------------------
def write_pem_from_env():
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")
    if not pem_content:
        raise ValueError("COINBASE_PEM_CONTENT not set")
    pem_path = "/tmp/coinbase.pem"
    with open(pem_path, "w", newline="\n") as f:
        f.write(pem_content.replace("\\n", "\n"))
    log(f"PEM written to {pem_path}")
    return pem_path

def load_private_key(pem_path):
    with open(pem_path, "rb") as f:
        key_data = f.read()
    key = serialization.load_pem_private_key(key_data, password=None, backend=default_backend())
    log("✅ PEM loaded successfully. Key type: " + str(type(key)))
    return key

# -------------------------------
# Build JWT
# -------------------------------
def build_jwt(key, org_id, kid):
    now = int(time.time())
    payload = {
        "sub": org_id,
        "iat": now,
        "exp": now + 300  # 5 minutes
    }
    headers = {
        "kid": kid
    }
    token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
    return token

# -------------------------------
# Verify JWT locally
# -------------------------------
def verify_jwt(token):
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        log("✅ JWT structure is valid")
        log("JWT header: " + str(header))
        log("JWT payload: " + str(payload))
    except Exception as e:
        log("❌ JWT verification failed: " + str(e))
        return False
    return True

# -------------------------------
# Test Coinbase endpoints
# -------------------------------
def test_coinbase(token):
    endpoints = {
        "Live": "https://api.exchange.coinbase.com/accounts",
        "Sandbox": "https://api-public.sandbox.pro.coinbase.com/accounts"
    }
    for name, url in endpoints.items():
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            log(f"{name} endpoint status: {resp.status_code}")
            log(f"{name} response (truncated): {resp.text[:500]}")
        except Exception as e:
            log(f"{name} request failed: {e}")

# -------------------------------
# Main
# -------------------------------
if __name__ == "__main__":
    log("=== Coinbase JWT Debug Script ===")

    pem_path = os.environ.get("COINBASE_PEM_PATH") or write_pem_from_env()
    org_id = os.environ.get("COINBASE_ORG_ID")
    kid = os.environ.get("COINBASE_JWT_KID")

    if not pem_path or not org_id or not kid:
        log("❌ Missing PEM_PATH, ORG_ID, or KID; cannot proceed")
        exit(1)

    key = load_private_key(pem_path)
    token = build_jwt(key, org_id, kid)

    log("Generated JWT (preview): " + token[:200])
    
    # ✅ Decode locally
    verify_jwt(token)

    # 🧪 Test both Coinbase endpoints
    test_coinbase(token)
