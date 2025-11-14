# debug_jwt_info.py
import os
import time
import base64
import json
from loguru import logger
import jwt  # pyjwt

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines if needed
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

# Detect if COINBASE_API_KEY is full path
if "organizations/" in API_KEY:
    sub = API_KEY  # full path
else:
    sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

logger.info(f"Using sub for JWT: {sub}")

# JWT payload
iat = int(time.time())
exp = iat + 300  # 5 min expiry
payload = {
    "sub": sub,
    "iat": iat,
    "exp": exp,
    "jti": str(iat)
}

# Generate JWT
try:
    token = jwt.encode(payload, PEM, algorithm="ES256")
    logger.info(f"✅ JWT generated successfully. Preview (first 100 chars): {token[:100]}")
except Exception as e:
    logger.error(f"Failed to generate JWT: {type(e).__name__}: {e}")
