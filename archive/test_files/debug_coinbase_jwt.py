# debug_coinbase_jwt.py
import os, time, datetime, json, base64
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

def ensure_pem(pem_str):
    # convert literal \n to real newlines if needed
    if "\\n" in pem_str:
        pem_str = pem_str.replace("\\n", "\n")
    return pem_str

API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT") or os.environ.get("COINBASE_PEM_B64")
KID = os.environ.get("COINBASE_JWT_KID")
SANDBOX = os.environ.get("SANDBOX", "true").lower() in ("1","true","yes")

if PEM_CONTENT and not PEM_CONTENT.startswith("-----BEGIN"):
    # assume base64
    try:
        PEM_CONTENT = base64.b64decode(PEM_CONTENT).decode("utf-8")
    except Exception:
        # maybe it's already raw but contains \n escapes
        PEM_CONTENT = PEM_CONTENT.replace("\\n", "\n")

PEM_CONTENT = ensure_pem(PEM_CONTENT)

print("DEBUG: API_KEY:", API_KEY)
print("DEBUG: KID:", KID)
print("DEBUG: PEM snippet (head):", PEM_CONTENT.splitlines()[0] if PEM_CONTENT else "MISSING")

# build JWT
now = int(time.time())
payload = {"sub": API_KEY, "iat": now, "exp": now + 300}
headers = {"alg": "ES256", "kid": KID}

private_key = serialization.load_pem_private_key(PEM_CONTENT.encode("utf-8"), password=None, backend=default_backend())
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
print("\n=== JWT ===\n")
print(token)
print("\n=== decoded header & payload ===\n")
h_b64, p_b64, s = token.split(".")
# safe decode
def b64d(s):
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s).decode("utf-8")

print("header:", json.loads(b64d(h_b64)))
print("payload:", json.loads(b64d(p_b64)))
print("\nServer UTC:", datetime.datetime.utcnow().isoformat())

# make a sandbox test (Bearer)
BASE = "https://api-public.sandbox.pro.coinbase.com" if SANDBOX else "https://api.coinbase.com"
headers_req = {"Authorization": f"Bearer {token}"}
try:
    r = requests.get(f"{BASE}/accounts", headers=headers_req, timeout=10)
    print("\nSandbox /accounts response:", r.status_code, r.text[:800])
except Exception as e:
    print("\nSandbox request failed:", e)
