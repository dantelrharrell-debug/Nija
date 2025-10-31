import os
import jwt
import time

COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_KEY_B64 = os.getenv("COINBASE_PEM_KEY_B64")

def get_jwt_token():
    now = int(time.time())
    payload = {
        "sub": COINBASE_API_KEY_ID,
        "iat": now,
        "exp": now + 300,  # 5 min expiry
        "jti": str(now)
    }
    key_bytes = base64.b64decode(COINBASE_PEM_KEY_B64)
    token = jwt.encode(payload, key_bytes, algorithm="ES256")
    return token
