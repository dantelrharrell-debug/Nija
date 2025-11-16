# Save as: test_jwt_and_fetch.py
import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ---- ENV NAMES (make sure these are set in Railway/Render or your shell) ----
# COINBASE_ORG_ID            (example: ce77e4ea-ecca-42ec-912a-b6b4455ab9d0)
# COINBASE_API_SUB           (full: organizations/.../apiKeys/<id>)
# COINBASE_API_KID           (optional; defaults to COINBASE_API_SUB)
# COINBASE_PEM_CONTENT      (optional: raw PEM block OR with literal "\n")
# COINBASE_PEM_PATH         (optional: path to PEM file inside container)

COINBASE_ORG_ID = os.getenv("COINBASE_OR_ID") or os.getenv("COINBASE_ORG_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB") or os.getenv("COINBASE_API_KEY_FULL") or os.getenv("COINBASE_API_KEY")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")

def load_pem_text():
    if COINBASE_PEM_CONTENT:
        # Accept either raw PEM or a string with literal "\n"
        pem = COINBASE_PEM_CONTENT
        # If the env contains literal backslash-n sequences, convert them
        if "\\n" in pem:
            pem = pem.replace("\\n", "\n")
        return pem.strip()
    if COINBASE_PEM_PATH:
        if not os.path.exists(COINBASE_PEM_PATH):
            raise SystemExit(f"PEM path not found: {COINBASE_PEM_PATH}")
        with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
            return f.read().replace('\r','').strip()
    raise SystemExit("No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

# Validate minimal env
if not COINBASE_ORG_ID or not COINBASE_API_SUB:
    raise SystemExit("Missing COINBASE_ORG_ID or COINBASE_API_SUB in env. Set them and retry.")

pem_text = load_pem_text()

# Try to load private key
try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode("utf-8"), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM:", e)
    raise

# Build JWT payload and headers
def make_jwt_for_path(request_path, method="GET", lifetime_seconds=120):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + lifetime_seconds,
        "sub": COINBASE_API_SUB.split("/")[-1] if COINBASE_API_SUB else None,
        "request_path": request_path,
        "method": method
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KID}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# Target path
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
token = make_jwt_for_path(path)

# Print details for debugging (do NOT share token publicly)
print("\n--- JWT PREVIEW ---")
print("JWT preview (first 120):", token[:120])
print("JWT header (unverified):", jwt.get_unverified_header(token))
print("JWT payload (unverified):", jwt.decode(token, options={"verify_signature": False}))

# Do the request
url = f"https://api.coinbase.com{path}"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-16"
}
print("\nRequest URL:", url)
print("Sending request...")

resp = requests.get(url, headers=headers, timeout=10)
print("HTTP status:", resp.status_code)
print("Response text:", resp.text)
if resp.status_code == 401:
    print("\n⚠️ 401 Unauthorized — check these in order:")
    print(" - COINBASE_API_SUB and COINBASE_API_KID must match the key shown in Coinbase (kid is often the full organizations/.../apiKeys/... path)")
    print(" - The key must have permissions (view/accounts, trade etc.)")
    print(" - The container/system clock must be correct (NTP).")
    print(" - Confirm request_path & method in JWT match the requested endpoint (they must match EXACTLY).")
else:
    print("\n✅ If status is 200, you're connected (accounts returned).")
