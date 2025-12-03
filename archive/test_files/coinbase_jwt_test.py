# coinbase_jwt_test.py
import os, time, requests, jwt, datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
PEM = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n").strip()

if not (COINBASE_ORG_ID and COINBASE_API_SUB and PEM):
    print("Missing env vars. Check COINBASE_ORG_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT.")
    raise SystemExit(1)

private_key = serialization.load_pem_private_key(PEM.encode(), password=None, backend=default_backend())

path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": COINBASE_API_SUB,
    "request_path": path,
    "method": "GET",
    "jti": f"dbg-{iat}"
}
headers_jwt = {"alg": "ES256", "kid": COINBASE_API_KID}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
print("\n=== JWT preview (first 200 chars) ===")
print(token[:200])
print("=== calling Coinbase", path, "===\n")

resp = requests.get("https://api.coinbase.com" + path, headers={
    "Authorization": f"Bearer {token}",
    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
    "Content-Type": "application/json"
}, timeout=10)

print("status:", resp.status_code)
print("body:", resp.text)
