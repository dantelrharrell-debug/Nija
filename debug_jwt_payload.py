# debug_jwt_payload.py
import os
import time
import jwt
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load environment
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines if needed
pem = PEM_RAW.replace("\\n", "\n") if "\\n" in PEM_RAW else PEM_RAW

# JWT payload
iat = int(time.time())
exp = iat + 300  # 5 min expiry
sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"  # adjust if API_KEY is full path

payload = {
    "sub": sub,
    "iat": iat,
    "exp": exp,
    "jti": str(iat)  # unique ID for JWT
}

logger.info("JWT Payload:")
logger.info(payload)

try:
    token = jwt.encode(payload, pem, algorithm="ES256")
    logger.info("\n✅ JWT Generated successfully!")
    logger.info(f"JWT preview: {token[:60]}...")  # just preview
except Exception as e:
    logger.error(f"Failed to generate JWT: {type(e).__name__}: {e}")
    
