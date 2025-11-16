# preflight_coinbase_jwt.py
import os
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib

# ----------------------------
# Load env vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")           # org UUID
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")   # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")         # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") # PEM block

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB or not COINBASE_PEM_CONTENT:
    raise SystemExit("Missing required env vars: COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT")

# ----------------------------
# Load PEM
# ----------------------------
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# ----------------------------
# PEM fingerprint (sha256) for verification
# ----------------------------
pem_bytes = pem_text.encode()
fingerprint = hashlib.sha256(pem_bytes).hexdigest()
print(f"🔹 PEM SHA256 fingerprint: {fingerprint}")

# ----------------------------
# Generate test JWT
# ----------------------------
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": COINBASE_API_KEY_ID,
    "request_path": f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "method": "GET"
}
headers_jwt = {"alg": "ES256", "kid": COINBASE_API_SUB}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    print("✅ JWT generated successfully")
    print("JWT header:", headers_jwt)
    print("JWT payload:", payload)
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    raise SystemExit(f"❌ Failed to generate JWT: {e}")

# ----------------------------
# ✅ Preflight complete
# ----------------------------
print("✅ Preflight check done. No Coinbase call made yet.")
print("Check that API_KEY_ID, API_SUB, and PEM fingerprint match Coinbase dashboard.")
