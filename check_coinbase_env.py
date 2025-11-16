# check_coinbase_env.py
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

print("=== Coinbase env / JWT diagnostic ===\n")

COINBASE_API_SUB = os.getenv("COINBASE_API_SUB") or os.getenv("COINBASE_API_KEY_FULL")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # optional short id
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

print("ENV CHECK")
print("COINBASE_API_SUB (present):", bool(COINBASE_API_SUB))
print("COINBASE_API_KEY (raw):", COINBASE_API_KEY)
print("COINBASE_API_KID (present):", bool(COINBASE_API_KID))
print("COINBASE_ORG_ID:", COINBASE_ORG_ID)
print("COINBASE_PEM_PATH:", COINBASE_PEM_PATH)
print("COINBASE_PEM_CONTENT (present):", bool(COINBASE_PEM_CONTENT))
print("local epoch time:", int(time.time()))
print("")

# Load PEM text (prefer content then path)
pem_text = None
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").replace('\r', '').strip().strip('"').strip("'")
    print("Loaded PEM from COINBASE_PEM_CONTENT (converted \\n -> newline).")
elif COINBASE_PEM_PATH:
    if not os.path.exists(COINBASE_PEM_PATH):
        raise SystemExit(f"PEM path not found: {COINBASE_PEM_PATH}")
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read().replace('\r', '').strip()
    print("Loaded PEM from COINBASE_PEM_PATH.")
else:
    raise SystemExit("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

# Try to load private key
try:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None, backend=default_backend())
    print("✅ PEM loaded OK")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# Normalize kid and api_key_id (sub)
if COINBASE_API_SUB:
    kid = COINBASE_API_KID
    api_key_id = COINBASE_API_SUB.split("/")[-1]
else:
    if COINBASE_API_KEY and "/" in COINBASE_API_KEY:
        kid = COINBASE_API_KEY
        api_key_id = COINBASE_API_KEY.split("/")[-1]
    else:
        api_key_id = COINBASE_API_KEY
        kid = api_key_id

print("Using API_KEY_ID (sub):", api_key_id)
print("Using kid header value:", kid)
print("")

# Build JWT for accounts path
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {"iat": iat, "exp": iat + 120, "sub": api_key_id, "request_path": path, "method": "GET"}
headers = {"alg": "ES256", "kid": kid}
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

print("JWT preview (first 80):", token[:80])
print("JWT header (unverified):", jwt.get_unverified_header(token))
print("JWT payload (unverified):", jwt.decode(token, options={"verify_signature": False}))
print("")
print("Request URL:", f"https://api.coinbase.com{path}")
print("Running test request now...")

# Do the request
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"}, timeout=10)

print("\nHTTP status:", resp.status_code)
print("Response text:", resp.text)
if resp.status_code == 401:
    print("\n⚠️ 401 Unauthorized — checklist:")
    print("- Confirm the API key displayed in Coinbase UI matches the API_KEY_ID above.")
    print("- Confirm the PEM you uploaded is the exact key downloaded when creating the API key.")
    print("- Confirm COINBASE_API_SUB and COINBASE_API_KID use the full path (organizations/.../apiKeys/...).")
    print("- Confirm the API key belongs to the org (COINBASE_ORG_ID).")
    print("- Confirm the key's permissions include 'view' (accounts) and are not revoked.")
    print("- Check container clock (local epoch printed above) vs real time.")
    print("- Try running the same curl locally using the generated JWT (paste the token into jwt.io to double-check header/payload).")
else:
    print("\n✅ Call succeeded (or returned non-401). Check JSON above for accounts.")
