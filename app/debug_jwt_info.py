# debug_jwt_info.py
import os, time, base64, json
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt  # pyjwt

logger.remove()
logger.add(lambda m: print(m, end=""))

API_KEY = os.environ.get("COINBASE_API_KEY", "")
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "")

def get_pem():
    if PEM_B64:
        try:
            decoded = base64.b64decode(PEM_B64).decode()
            logger.info("Loaded PEM from COINBASE_PEM_B64 (base64).")
            return decoded
        except Exception as e:
            logger.error(f"Failed to decode COINBASE_PEM_B64: {e}")
    if "\\n" in PEM_RAW:
        logger.info("Detected literal \\n sequences in COINBASE_PEM_CONTENT; replacing with real newlines.")
        return PEM_RAW.replace("\\n", "\n")
    return PEM_RAW

pem = get_pem()
logger.info(f"PEM length: {len(pem)}")
if not pem or "BEGIN EC PRIVATE KEY" not in pem:
    logger.error("PEM appears missing or malformed. Paste the full PEM (BEGIN/END lines) or use COINBASE_PEM_B64.")
else:
    try:
        priv = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
        pub = priv.public_key()
        pem_pub = pub.public_bytes(encoding=serialization.Encoding.PEM,
                                   format=serialization.PublicFormat.SubjectPublicKeyInfo)
        logger.info("✅ Private key loaded. Public key preview:")
        for line in pem_pub.decode().splitlines()[:10]:
            logger.info(line)
    except Exception as e:
        logger.error(f"Failed to load PEM: {type(e).__name__}: {e}")

# Build simple JWT for inspection (won't be signed with Coinbase-specific headers but good to check claims)
sub = API_KEY if "organizations/" in API_KEY else (f"organizations/{ORG_ID}/apiKeys/{API_KEY}" if ORG_ID and API_KEY else API_KEY)
payload = {
    "sub": sub,
    "iat": int(time.time()),
    "exp": int(time.time()) + 30
}
try:
    # Try signing to see if key works for creating JWT
    token = jwt.encode(payload, pem, algorithm="ES256")
    logger.info("Generated JWT (preview):")
    logger.info(token[:80] + "...")
    # decode header/payload for inspection
    header_b64, payload_b64, sig = token.split(".")
    def b64d(x): 
        padding = '=' * (-len(x) % 4)
        return json.loads(base64.urlsafe_b64decode(x + padding).decode())
    logger.info("JWT header:")
    logger.info(json.dumps(b64d(header_b64), indent=2))
    logger.info("JWT payload:")
    logger.info(json.dumps(b64d(payload_b64), indent=2))
except Exception as e:
    logger.error(f"Failed to sign JWT with provided PEM: {type(e).__name__}: {e}")
