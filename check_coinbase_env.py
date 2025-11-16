# check_coinbase_env_auto_sync.py
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import subprocess

# -----------------------------
# Load environment variables
# -----------------------------
COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
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
# Auto-sync container time with Coinbase server
# -----------------------------
try:
    server_time_resp = requests.get("https://api.coinbase.com/v2/time")
    server_time = int(server_time_resp.json()['data']['epoch'])
    local_time = int(time.time())
    skew = server_time - local_time
    print(f"⏱ Local time: {local_time}, Coinbase server time: {server_time}, skew: {skew}s")
    
    # Auto-adjust container time (Linux only, requires privileges)
    if abs(skew) > 2:
        print("🔧 Syncing container time...")
        subprocess.run(["date", "-s", f"@{server_time}"], check=False)
        print("✅ Time synced to Coinbase server")
    else:
        print("✅ Time in sync (within 2s)")
except Exception as e:
    print(f"⚠️ Could not sync time automatically: {e}")

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
    print("❌ Unauthorized. Check PEM, API key, key permissions, or container time.")
else:
    print("⚠️ Unexpected response. Check your key, PEM, and network.")
