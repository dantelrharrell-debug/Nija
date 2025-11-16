import os
import time
import datetime
import requests
import jwt  # PyJWT

# =========================
# Coinbase API environment
# =========================
COINBASE_ORG_ID = os.environ["COINBASE_ORG_ID"]
COINBASE_API_SUB = os.environ["COINBASE_API_SUB"]  # full path e.g. organizations/<org>/apiKeys/<apiKeyId>
COINBASE_API_KID = os.environ.get("COINBASE_API_KID") or COINBASE_API_SUB
COINBASE_PEM_CONTENT = os.environ["COINBASE_PEM_CONTENT"].replace("\\n", "\n")  # multi-line key

# Load private key
private_key = COINBASE_PEM_CONTENT

# =========================
# Build request info
# =========================
coinbase_path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
method = "GET"

# =========================
# Build JWT payload
# =========================
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,               # expires in 2 minutes
    "sub": COINBASE_API_SUB,
    "request_path": coinbase_path,
    "method": method,
    "jti": f"dbg-{iat}"
}

# JWT headers
headers_jwt = {
    "alg": "ES256",
    "kid": COINBASE_API_KID,
    "typ": "JWT"
}

# =========================
# Encode JWT
# =========================
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
print("DEBUG JWT (first 200 chars):", token[:200])

# =========================
# Make API request
# =========================
url = "https://api.coinbase.com" + coinbase_path
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers, timeout=10)
print("Response status:", response.status_code)
print("Response body:", response.text)
