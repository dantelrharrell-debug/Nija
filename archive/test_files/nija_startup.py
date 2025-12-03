import os, time, requests, jwt, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Load env
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")  # full path
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")            # short id
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
CB_VERSION = "2025-11-12"

if not all([COINBASE_API_KEY, COINBASE_ORG_ID, COINBASE_PEM_PATH or COINBASE_PEM_CONTENT]):
    sys.exit("❌ Missing Coinbase credentials in env")

# -----------------------------
# Load PEM
# -----------------------------
pem_text = None
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n","\n").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        sys.exit(f"❌ PEM path not found: {COINBASE_PEM_PATH}")
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()

try:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None, backend=default_backend())
    print("✅ PEM loaded successfully")
except Exception as e:
    sys.exit(f"❌ Failed to load PEM: {e}")

# -----------------------------
# Normalize JWT fields
# -----------------------------
if COINBASE_API_KEY_FULL:
    kid = COINBASE_API_KEY_FULL
    api_key_id = COINBASE_API_KEY_FULL.split("/")[-1]
else:
    api_key_id = COINBASE_API_KEY
    kid = COINBASE_API_KEY_FULL or COINBASE_API_KEY  # full path preferred

print(f"Using API_KEY_ID (sub): {api_key_id}")
print(f"Using kid header: {kid}")

# -----------------------------
# Sync container time with Coinbase
# -----------------------------
try:
    resp = requests.get("https://api.coinbase.com/v2/time")
    resp.raise_for_status()
    server_epoch = resp.json()["data"]["epoch"]
    local_epoch = int(time.time())
    skew = server_epoch - local_epoch
    if abs(skew) > 5:
        print(f"⚠️ Clock skew detected: {skew} sec. Adjusting local time for JWT...")
        time_offset = skew
    else:
        time_offset = 0
except Exception as e:
    print("⚠️ Could not sync time with Coinbase. Proceeding without offset.")
    time_offset = 0

# -----------------------------
# Build JWT
# -----------------------------
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time()) + time_offset
payload = {"iat": iat, "exp": iat + 120, "sub": api_key_id, "request_path": path, "method": "GET"}
headers = {"alg": "ES256", "kid": kid}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
print("JWT preview (first 80 chars):", token[:80])

# -----------------------------
# Test JWT
# -----------------------------
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": CB_VERSION})
if resp.status_code != 200:
    sys.exit(f"❌ Failed to fetch Coinbase accounts. Status: {resp.status_code} | Response: {resp.text}")
else:
    print("✅ Coinbase JWT test passed. Accounts accessible.")
    print(resp.json())

# -----------------------------
# Start your bot here
# -----------------------------
print("🚀 Nija Bot ready to trade!")
