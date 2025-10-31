# nija_coinbase_jwt.py
import os
import time
import jwt
import logging
import base64
from threading import Lock
import re

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not (KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_API_KEY_ID or COINBASE_ORG_ID missing from env. JWT generation will fail until they are set.")

_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()


def _looks_like_base64(s: str) -> bool:
    if not s:
        return False
    s_clean = re.sub(r"\s+", "", s.strip())
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", s_clean)) and (len(s_clean) % 4 == 0 or len(s_clean) > 40)


def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool = False):
    """
    Normalize PEM input for jwt ES256 signing.
    Returns bytes (never str) to avoid UnicodeDecodeErrors.
    Supports:
      - raw PEM string
      - escaped \n sequences
      - base64 of full PEM (from_b64=True)
      - base64 body only
    """
    if not raw_pem:
        raise ValueError("No PEM provided")

    # If env is base64 PEM, decode to bytes
    if from_b64:
        try:
            decoded_bytes = base64.b64decode(raw_pem)
            return decoded_bytes  # leave as bytes
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to decode base64 PEM: %s", e)
            raise

    # raw_pem is str at this point
    if isinstance(raw_pem, str):
        # convert literal \n to real newlines
        if "\\n" in raw_pem:
            raw_pem = raw_pem.replace("\\n", "\n")
        raw_pem = raw_pem.strip()
        # remove surrounding quotes if any
        if (raw_pem.startswith('"') and raw_pem.endswith('"')) or (raw_pem.startswith("'") and raw_pem.endswith("'")):
            raw_pem = raw_pem[1:-1].strip()
        # If only base64 body, wrap in PEM headers
        if _looks_like_base64(raw_pem):
            body = "".join(raw_pem.split())
            wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
            pem_full = b"-----BEGIN EC PRIVATE KEY-----\n" + wrapped.encode() + b"\n-----END EC PRIVATE KEY-----\n"
            return pem_full
        return raw_pem.encode()  # str PEM -> bytes

    # If already bytes, return as-is
    return raw_pem


def _build_jwt():
    """
    Build a short-lived ES256 JWT for Coinbase API auth.
    """
    pem_b64_env = os.environ.get("COINBASE_PEM_KEY_B64")
    raw_pem_env = os.environ.get("COINBASE_PEM_KEY")

    raw_pem = None
    from_b64 = False
    if pem_b64_env:
        raw_pem = pem_b64_env
        from_b64 = True
    elif raw_pem_env:
        raw_pem = raw_pem_env
        from_b64 = False
    else:
        raise ValueError("Missing COINBASE_PEM_KEY or COINBASE_PEM_KEY_B64 environment variable")

    try:
        pem = _sanitize_and_normalize_pem(raw_pem, from_b64=from_b64)
    except Exception as e:
        logger.error("[NIJA-JWT] PEM sanitization/decoding failed: %s", e)
        raise

    # sanity check
    if not isinstance(pem, bytes):
        pem = pem.encode()
    if b"PRIVATE KEY" not in pem:
        logger.error("[NIJA-JWT] PEM does not appear valid. First 100 bytes: %s", pem[:100])
        raise ValueError("Normalized PEM does not contain expected header/trailer")

    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 minutes
        "sub": ORG_ID,
        "kid": KEY_ID
    }

    try:
        token = jwt.encode(payload, pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode()
        return token, payload["exp"]
    except Exception as e:
        logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
        logger.error("[NIJA-JWT] Common causes: PEM formatting lost linebreaks, PEM is corrupted, or key is not a private key.")
        logger.error("[NIJA-JWT] Tips: set COINBASE_PEM_KEY to full multi-line PEM, or COINBASE_PEM_KEY_B64 to base64 of full PEM.")
        raise


def get_jwt_token():
    """
    Returns a cached JWT, regenerating if expired or missing.
    Safe for concurrent calls.
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
            logger.error("[NIJA-JWT] Unable to create JWT: %s", e)
            raise


# ------------------------------
# Debug helper
# ------------------------------
def debug_print_jwt_payload():
    try:
        token = get_jwt_token()
        import json
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode()
            logger.info("[NIJA-JWT-DEBUG] JWT payload: %s", payload_json)
    except Exception as e:
        logger.debug("[NIJA-JWT-DEBUG] Could not decode JWT payload: %s", e)
