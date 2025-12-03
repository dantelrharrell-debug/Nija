# debug_jwt.py
import os
import time
import jwt  # pyjwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load env vars
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY_RAW = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

# Detect if API_KEY is already full path
if "organizations/" in API_KEY_RAW:
    sub = API_KEY_RAW  # full path
else:
    sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY_RAW}"

logger.info(f"✅ Sub claim: {sub}")
logger.info(f"✅ PEM first 50 chars: {PEM[:50]}")

# Load private key
try:
    priv = serialization.load_pem_private_key(
        PEM.encode(), password=None, backend=default_backend()
    )
    pub = priv.public_key()
    pem_pub = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    logger.info("✅ Private key loaded successfully.")
    logger.info("Public key preview:\n" + "\n".join(pem_pub.decode().splitlines()[:3]))
except Exception as e:
    logger.error(f"❌ Failed to load PEM: {type(e).__name__}: {e}")
    raise

# JWT payload
iat = int(time.time())
exp = iat + 30  # short expiration for debug
payload = {
    "sub": sub,
    "iat": iat,
    "exp": exp
}

# Encode JWT
try:
    token = jwt.encode(payload, priv, algorithm="ES256")
    logger.info(f"✅ JWT successfully generated. First 50 chars:\n{token[:50]}")
except Exception as e:
    logger.error(f"❌ JWT encode failed: {type(e).__name__}: {e}")
    raise
