# nija_coinbase_jwt.py
import os
import time
import jwt
import logging
import base64
from threading import Lock

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not (KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_API_KEY_ID or COINBASE_ORG_ID missing from env. JWT generation will fail until they are set.")

_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()

def _looks_like_base64(s: str) -> bool:
    import re
    if not s:
        return False
    s_compact = re.sub(r"\s+", "", s)
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", s_compact)) and len(s_compact) > 40

def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool=False) -> str:
    """
    Return a well-formed PEM string.
    Handles raw PEM, escaped \n, or base64 of full PEM.
    """
    if not raw_pem:
        raise ValueError("No PEM provided")

    # If it's base64-encoded full PEM, decode safely
    if from_b64:
        try:
            # decode as bytes, don't force UTF-8 yet
            decoded_bytes = base64.b64decode(raw_pem)
            raw_pem = decoded_bytes.decode("utf-8")  # should be valid text now
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to decode base64 PEM: %s", e)
            raise

    # Replace literal \n sequences
    if "\\n" in raw_pem:
        raw_pem = raw_pem.replace("\\n", "\n")

    # Strip surrounding quotes
    raw_pem = raw_pem.strip()
    if (raw_pem.startswith('"') and raw_pem.endswith('"')) or (raw_pem.startswith("'") and raw_pem.endswith("'")):
        raw_pem = raw_pem[1:-1].strip()

    # If PEM already contains headers, normalize
    if "-----BEGIN" in raw_pem and "-----END" in raw_pem:
        if not raw_pem.endswith("\n"):
            raw_pem += "\n"
        return raw_pem

    # If looks like base64 body, wrap with headers
    if _looks_like_base64(raw_pem):
        logger.info("[NIJA-JWT] Detected base64 PEM body; wrapping with BEGIN/END headers")
        body = "".join(raw_pem.split())
        wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        return f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"

    # Otherwise, return as-is (jwt will fail later with clear message)
    return raw_pem

def _build_jwt():
    """
    Build a short-lived JWT signed with PEM key from env.
    """
    pem_b64_env = os.environ.get("COINBASE_PEM_KEY_B64")
    raw_pem_env = os.environ.get("COINBASE_PEM_KEY")

    if pem_b64_env:
        raw_pem = pem_b64_env
        from_b64 = True
    elif raw_pem_env:
        raw_pem = raw_pem_env
        from_b64 = False
    else:
        raise ValueError("Missing COINBASE_PEM_KEY or COINBASE_PEM_KEY_B64")

    pem = _sanitize_and_normalize_pem(raw_pem, from_b64=from_b64)

    # sanity check
    if "-----BEGIN" not in pem or "PRIVATE KEY" not in pem:
        raise ValueError("Normalized PEM does not appear valid")

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
        raise

def get_jwt_token():
    """
    Returns cached JWT, regenerating if expired or missing.
    """
    with _LOCK:
        now = int(time.time())
        if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] - 10 > now:
            return _TOKEN_CACHE["token"]
        token, exp = _build_jwt()
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["exp"] = exp
        logger.info("[NIJA-JWT] Generated new JWT (exp=%s)", exp)
        return token

# -----------------------------
# Debug helper: decode & log JWT payload (no signature verification)
# -----------------------------
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
