import os
import time
import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load environment variables ---
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")
API_KEY_ID = os.environ.get("COINBASE_API_KEY")  # This is the key ID (kid)

if not ORG_ID or not PEM_RAW or not API_KEY_ID:
    raise Exception("Missing COINBASE_ORG_ID, COINBASE_PEM_CONTENT, or COINBASE_API_KEY")

# --- Prepare PEM key ---
try:
    pem_bytes = PEM_RAW.encode()  # ensure bytes
    private_key = serialization.load_pem_private_key(
        pem_bytes,
        password=None,
        backend=default_backend()
    )
except Exception as e:
    raise Exception(f"Failed to load PEM key: {e}")

# --- Generate JWT ---
now = int(time.time())
payload = {
    "iat": now,
    "exp": now + 300,   # 5 minutes expiration
    "sub": ORG_ID
}
headers = {
    "kid": API_KEY_ID,
    "alg": "ES256"
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    print("JWT generated successfully:", token[:50], "...")
except Exception as e:
    raise Exception(f"Failed to generate JWT: {e}")

# --- Test API call ---
url = f"https://api.coinbase.com/brokerage/organizations/{ORG_ID}/accounts"
headers = {"Authorization": f"Bearer {token}"}

response = requests.get(url, headers=headers)
print("Status Code:", response.status_code)
print("Response Body:", response.text)


def sign_request(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    signature = sk.sign(message.encode())
    signature_b64 = base64.b64encode(signature).decode()
    return timestamp, signature_b64


def get_accounts():
    path = "/v2/accounts"
    ts, sig = sign_request("GET", path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.get(BASE_URL + path, headers=headers, timeout=15)
    if resp.status_code != 200:
        log.error("Status=%s Body=%s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    try:
        accounts = get_accounts()
        for acct in accounts.get("data", []):
            if acct["balance"]["currency"] == "USD":
                print("USD Spot Balance:", acct["balance"]["amount"])
    except Exception as e:
        log.exception("Failed to fetch accounts: %s", e)
