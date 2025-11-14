import os, jwt, time, base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

pem_content = os.environ.get("COINBASE_PEM_CONTENT")
org_id = os.environ.get("COINBASE_ORG_ID")
api_key = os.environ.get("COINBASE_API_KEY")

# Load PEM
private_key = serialization.load_pem_private_key(
    pem_content.encode(), password=None, backend=default_backend()
)

# Build JWT
payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + 300,
    "jti": "test123456"
}

jwt_token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": api_key})
print("JWT Generated Successfully:", jwt_token)
