import os, time, requests, jwt, datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")  # full path
COINBASE_API_KID = os.getenv("COINBASE_API_KID") or COINBASE_API_SUB
pem = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n").strip()

private_key = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())

path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {"iat": iat, "exp": iat + 120, "sub": COINBASE_API_SUB, "request_path": path, "method":"GET", "jti": f"dbg-{iat}"}
headers = {"alg":"ES256", "kid": COINBASE_API_KID}
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
print("JWT preview:", token[:200])
resp = requests.get("https://api.coinbase.com"+path, headers={"Authorization":f"Bearer {token}", "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d")}, timeout=10)
print("status:", resp.status_code)
print("body:", resp.text)
