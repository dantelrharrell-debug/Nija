import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Load environment variables
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")  # full org path
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")            # short id
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
CB_API_HOST = "https://api.coinbase.com"

print("🔍 Checking Coinbase environment...")
print("COINBASE_API_KEY_FULL:", bool(COINBASE_API_KEY_FULL))
print("COINBASE_API_KEY:", COINBASE_API_KEY)
print("COINBASE_ORG_ID:", COINBASE_ORG_ID)
print("COINBASE_PEM_PATH:", COINBASE_PEM_PATH)
print("COINBASE_PEM_CONTENT:", bool(COINBASE_PEM_CONTENT))

# -----------------------------
# Load PEM (prefer content first)
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
    kid = COINBASE_API_KEY
    api_key_id = COINBASE_API_KEY

print("Using API_KEY_ID (sub):", api_key_id)
print("Using kid header value:", kid)

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
print("JWT header (unverified):", jwt.get_unverified_header(token))
print("JWT payload (unverified):", jwt.decode(token, options={"verify_signature": False}))

# -----------------------------
# Test Coinbase request
# -----------------------------
print("\n🌐 Sending test request to Coinbase...")
resp = requests.get(
    f"{CB_API_HOST}{path}",
    headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12"
    },
    timeout=10
)

if resp.status_code == 200:
    accounts = resp.json().get("data", [])
    funded = [a for a in accounts if float(a.get("balance", {}).get("amount", 0)) > 0]
    print(f"✅ Accounts fetched successfully. Total: {len(accounts)}, Funded: {len(funded)}")
    for a in funded:
        print(f" - {a.get('name')} | {a.get('balance')}")
elif resp.status_code == 401:
    print("❌ Unauthorized! Check API key, org, PEM, and permissions.")
    print("Response:", resp.text)
else:
    print(f"❌ Failed to fetch accounts. Status: {resp.status_code}")
    print("Response:", resp.text)
