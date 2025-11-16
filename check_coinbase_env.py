# check_coinbase_env.py
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Load environment variables
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")  # organizations/.../apiKeys/<id>
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")            # short id
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

print("ENV CHECK")
print("COINBASE_API_KEY_FULL:", bool(COINBASE_API_KEY_FULL))
print("COINBASE_API_KEY (raw):", COINBASE_API_KEY)
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
        raise SystemExit(f"❌ PEM path not found: {COINBASE_PEM_PATH}")
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()
else:
    raise SystemExit("❌ No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded OK")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# -----------------------------
# Normalize API key ID / kid
# -----------------------------
if COINBASE_API_KEY_FULL:
    kid = COINBASE_API_KEY_FULL
    api_key_id = COINBASE_API_KEY_FULL.split("/")[-1]
else:
    if COINBASE_API_KEY and "/" in COINBASE_API_KEY:
        kid = COINBASE_API_KEY
        api_key_id = COINBASE_API_KEY.split("/")[-1]
    else:
        api_key_id = COINBASE_API_KEY
        kid = api_key_id

print("Using API_KEY_ID (sub):", api_key_id)
print("Using kid header value:", kid)

# -----------------------------
# Build JWT
# -----------------------------
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,  # 2 minutes expiration
    "sub": api_key_id,
    "request_path": path,
    "method": "GET"
}
headers = {"alg": "ES256", "kid": kid}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
print("JWT preview (first 80):", token[:80])
print("JWT header (unverified):", jwt.get_unverified_header(token))
print("JWT payload (unverified):", jwt.decode(token, options={"verify_signature": False}))

# -----------------------------
# Test request
# -----------------------------
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print("HTTP status:", resp.status_code)
print("Response text:", resp.text)

if resp.status_code == 200:
    print("🎯 Coinbase API connection OK! You can trade now.")
elif resp.status_code == 401:
    print("❌ Unauthorized. Check PEM, API key, or key permissions.")
else:
    print("⚠️ Unexpected response. Check your key and network.")
