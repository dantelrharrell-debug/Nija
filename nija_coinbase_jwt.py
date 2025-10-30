# nija_coinbase_jwt.py
import os
import time
import jwt
import logging
from threading import Lock

logger = logging.getLogger("nija_coinbase_jwt")

# Read env
PEM_KEY = os.environ.get("COINBASE_PEM_KEY")
KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not (PEM_KEY and KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_PEM_KEY, COINBASE_API_KEY_ID or COINBASE_ORG_ID missing from env.")

_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()

def _build_jwt():
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,   # 5 minutes
        "sub": ORG_ID,
        "kid": KEY_ID
    }
    # PyJWT will accept PEM string
    token = jwt.encode(payload, PEM_KEY, algorithm="ES256")
    # PyJWT may return bytes or str depending on version
    if isinstance(token, bytes):
        token = token.decode()
    return token, payload["exp"]

def get_jwt_token():
    """
    Returns a cached JWT, regenerating if expired or missing.
    Safe to call concurrently.
    """
    with _LOCK:
        now = int(time.time())
        if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] - 10 > now:
            return _TOKEN_CACHE["token"]
        try:
            token, exp = _build_jwt()
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["exp"] = exp
            logger.info("[NIJA-JWT] Generated new JWT (exp=%s)", exp)
            return token
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
            raise
