import os
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ----------------------------
# Load env vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")           # org UUID
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")   # short UUID (last part)
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")         # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") # PEM block

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
# Generate a test JWT
# ----------------------------
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 60,  # 1 minute validity
    "sub": COINBASE_API_KEY_ID,
    "request_path": f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "method": "GET"
}

headers_jwt = {"alg": "ES256", "kid": COINBASE_API_SUB}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    print("✅ JWT generated successfully")
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    raise SystemExit(f"❌ Failed to generate JWT: {e}")

# ----------------------------
# Test decode to check PEM/key pairing
# ----------------------------
try:
    decoded = jwt.decode(token, private_key.public_key(), algorithms=["ES256"], options={"verify_exp": False})
    print("✅ JWT decodes correctly with this PEM")
    print("Decoded payload:", decoded)
except Exception as e:
    print(f"❌ JWT failed to decode — PEM may not match key: {e}")
