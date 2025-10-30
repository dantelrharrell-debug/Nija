import os
import jwt
import time

def get_jwt_token():
    """
    Generates a JWT token for Coinbase API using PEM key stored in env.
    """
    pem_key = os.environ["COINBASE_PEM_KEY"]
    org_id = os.environ["COINBASE_ORG_ID"]
    key_id = os.environ["COINBASE_API_KEY_ID"]

    iat = int(time.time())
    exp = iat + 300  # 5 minutes validity

    payload = {
        "iat": iat,
        "exp": exp,
        "sub": org_id,
        "kid": key_id
    }

    token = jwt.encode(payload, pem_key, algorithm="ES256")
    return token
