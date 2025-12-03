# Save as check_coinbase_jwt.py and run inside container: python check_coinbase_jwt.py
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Load env
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")  # organizations/.../apiKeys/<id>
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")            # short id
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

print("ENV CHECK")
print("COINBASE_API_KEY_FULL:", bool(COINBASE_API_KEY_FULL))
print("COINBASE_API_KEY:", COINBASE_API_KEY)
print("COINBASE_ORG_ID:", COINBASE_ORG_ID)
print("COINBASE_PEM_PATH:", COINBASE_PEM_PATH)
print("COINBASE_PEM_CONTENT:", bool(COINBASE_PEM_CONTENT))

# -----------------------------
# Load PEM
# -----------------------------
pem_text = None
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        raise SystemExit(f"PEM path not found: {COINBASE_PEM_PATH}")
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()
else:
    raise SystemExit("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None, backend=default_backend())
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# -----------------------------
# Normalize key
# -----------------------------
if COINBASE_API_KEY_FULL:
    kid = COINBASE_API_KEY_FULL
    api_key_id = COINBASE_API_KEY_FULL.split("/")[-1]
else:
    api_key_id = COINBASE_API_KEY
    kid = f"organizations/{COINBASE_ORG_ID}/apiKeys/{api_key_id}"

print("API_KEY_ID (sub):", api_key_id)
print("KID header:", kid)

# -----------------------------
# Build JWT
# -----------------------------
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": api_key_id,
    "request_path": path,
    "method": "GET"
}
headers = {"alg": "ES256", "kid": kid}
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

print("JWT preview (first 80 chars):", token[:80])
print("JWT header:", jwt.get_unverified_header(token))
print("JWT payload:", jwt.decode(token, options={"verify_signature": False}))

# -----------------------------
# Test API request
# -----------------------------
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print("Request URL:", url)
print("HTTP status:", resp.status_code)
print("Response:", resp.text)

# -----------------------------
# Advice
# -----------------------------
if resp.status_code == 401:
    print("⚠️ 401 Unauthorized - likely causes:")
    print("- PEM does not match API key")
    print("- Key permissions do not allow access to this org")
    print("- Org ID mismatch")
    print("- JWT iat/exp invalid (clock skew)")
else:
    print("✅ Success! Accounts fetched correctly.")
