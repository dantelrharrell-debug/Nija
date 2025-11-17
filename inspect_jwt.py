# inspect_jwt.py
import time
import json
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ---------- Replace / confirm values (already filled from your input) ----------
ORG = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
KID = "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
# PEM (converted to multiline)
PEM = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----"""

# ---------- Derived / fixed values ----------
REQUEST_PATH = f"/api/v3/brokerage/organizations/{ORG}/key_permissions"
BASE_URL = "https://api.coinbase.com"

def load_private_key(pem_text: str):
    try:
        key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None, backend=default_backend())
        return key
    except Exception as e:
        print("❌ Failed to parse PEM:", e)
        return None

def generate_jwt(key_obj, kid: str, org: str, path: str, method: str="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": f"/organizations/{org}/apiKeys/{kid}",
        "request_path": path,
        "method": method.upper(),
        "jti": f"inspect-{iat}"
    }
    headers = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    try:
        token = jwt.encode(payload, key_obj, algorithm="ES256", headers=headers)
        return token, payload, headers
    except Exception as e:
        print("❌ Failed to encode JWT:", e)
        return None, payload, headers

def call_key_permissions(token: str, org: str):
    url = BASE_URL + f"/api/v3/brokerage/organizations/{org}/key_permissions"
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": time.strftime("%Y-%m-%d"),
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.status_code, resp.text
    except Exception as e:
        return None, str(e)

def main():
    print("\n=== Inspect JWT & call /key_permissions ===\n")
    key_obj = load_private_key(PEM)
    if not key_obj:
        print("Cannot load private key. Fix PEM and try again.")
        return

    token, payload, headers = generate_jwt(key_obj, KID, ORG, REQUEST_PATH, method="GET")
    if not token:
        print("JWT generation failed.")
        return

    # token may be bytes on some PyJWT versions; ensure str
    if isinstance(token, bytes):
        token = token.decode()

    print("TOKEN (first 300 chars):\n", token[:300], ("\n...[truncated]" if len(token) > 300 else ""), "\n")
    print("JWT payload (unverified):")
    print(json.dumps(payload, indent=2))
    print("\nJWT header (sent):")
    print(json.dumps(headers, indent=2))

    # decode unverified to double-check
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        print("\nDECODED (unverified):")
        print(json.dumps(decoded, indent=2))
    except Exception as e:
        print("Warning: couldn't decode JWT unverified:", e)

    print("\nCalling Coinbase /key_permissions ...")
    status, body = call_key_permissions(token, ORG)
    print("HTTP status:", status)
    print("Response body:\n", body)

    if status == 200:
        print("\n✅ Success: Coinbase accepted the JWT. Key permissions returned.")
    elif status == 401:
        print("\n❌ 401 Unauthorized: Coinbase rejected the JWT.")
        print("Check (in order):")
        print("  - The API key's ORG & KID match exactly the 'sub' and header.kid.")
        print("  - The PEM is the private key that was used to generate that API key.")
        print("  - If the key has IP restrictions, whitelist the outbound IP from your container.")
    else:
        print("\nℹ️ Non-200 response. Inspect the response body for details.")

if __name__ == "__main__":
    main()
