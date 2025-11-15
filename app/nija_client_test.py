# /app/nija_client_test.py
import os, time, jwt, requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import datetime

def load_private_key(path):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

def make_jwt(private_key, org_id, kid):
    iat = int(time.time())
    payload = {"sub": org_id, "iat": iat, "exp": iat + 300}
    headers = {"kid": kid} if kid else {}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

def test_call(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": os.environ.get("CB_API_VERSION", "2025-01-01"),
    }
    return requests.get("https://api.coinbase.com/v2/accounts", headers=headers, timeout=15)

if __name__ == "__main__":
    PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
    ORG_ID = os.environ.get("COINBASE_ORG_ID")
    KID = os.environ.get("COINBASE_JWT_KID")

    print("PEM_PATH:", PEM_PATH)
    print("ORG_ID:", ORG_ID)
    print("KID  :", KID)
    print("Server UTC time:", datetime.datetime.utcnow().isoformat())

    key = load_private_key(PEM_PATH)
    token = make_jwt(key, ORG_ID, KID)
    print("\nJWT (first 200 chars):", token[:200])

    # show header & payload (no signature verify) for debugging
    print("\nJWT header (unverified):", jwt.get_unverified_header(token))
    print("JWT payload (unverified):", jwt.decode(token, options={"verify_signature": False}))

    resp = test_call(token)
    print("\nCoinbase response status:", resp.status_code)
    print("Coinbase response text (truncated):", resp.text[:1000])
