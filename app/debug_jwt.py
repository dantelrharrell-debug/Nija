# /app/debug_jwt.py — debug JWT + accounts test
import os, time, json, sys
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

def log(*a, **k): 
    print(*a, **k); sys.stdout.flush()

key_id = os.getenv("COINBASE_API_KEY_ID")
pem = os.getenv("COINBASE_PEM")
org = os.getenv("COINBASE_ORG_ID")
log("ENV SNAPSHOT:", "KEY_ID set?" , bool(key_id), "PEM set?", bool(pem), "ORG set?", bool(org))
if pem:
    log("PEM length (chars):", len(pem))
    # show first/last 50 chars (do NOT print the PEM itself)
    log("PEM head:", pem[:50].replace("\n","\\n"))
    log("PEM tail:", pem[-50:].replace("\n","\\n"))

# Attempt to load PEM
try:
    private_key = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
    log("Loaded PEM -> OK (private key object type)", type(private_key))
except Exception as e:
    log("ERROR loading PEM:", e)
    raise SystemExit(1)

# Build JWT
iat = int(time.time())
payload = {"iat": iat, "exp": iat+300, "sub": key_id, "request_path": f"/organizations/{org}/accounts", "method": "GET"}
token = jwt.encode(payload, private_key, algorithm="ES256")
log("SAMPLE JWT (first 200 chars):", token[:200])

# Try the request
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{org}/accounts"
headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"}
log("Requesting", url)
resp = requests.get(url, headers=headers)
log("HTTP status:", resp.status_code)
try:
    data = resp.json()
    log("Response JSON keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    log("Response (first 500 chars):", json.dumps(data)[:500])
except Exception:
    log("Response text (first 500 chars):", resp.text[:500])
