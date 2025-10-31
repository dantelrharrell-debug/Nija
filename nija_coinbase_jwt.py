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

# Environment variables
KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not (KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_API_KEY_ID or COINBASE_ORG_ID missing. JWT generation will fail until they are set.")

# Token cache for short-lived JWT
_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()

def _looks_like_base64(s: str) -> bool:
    if not s:
        return False
    s_clean = re.sub(r"\s+", "", s)
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", s_clean)) and (len(s_clean) % 4 == 0 or len(s_clean) > 40)

def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool=False) -> str:
    """
    Returns a normalized PEM string.
    Handles full PEM, base64 body, escaped \n sequences, or base64 of PEM.
    """
    if not raw_pem:
        raise ValueError("No PEM provided for JWT")

    pem = raw_pem.strip()

    if from_b64:
        try:
            # Decode base64 of full PEM
            s = re.sub(r"\s+", "", pem)
            padded = s + ("=" * (-len(s) % 4))
            pem = base64.b64decode(padded).decode("utf-8")
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to decode base64 PEM: %s", e)
            raise

    # Handle literal "\n" sequences
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")

    # Strip quotes
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1].strip()

    # If PEM already has headers, ensure proper formatting
    if "-----BEGIN" in pem and "-----END" in pem:
        pem = pem.strip()
        if not pem.endswith("\n"):
            pem += "\n"
        return pem

    # If looks like base64 body only, wrap with PEM headers
    if _looks_like_base64(pem):
        logger.info("[NIJA-JWT] Detected base64 PEM body; wrapping with headers")
        body = "".join(pem.split())
        wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        return f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"

    # Otherwise return as-is
    return pem

def _build_jwt():
    """
    Build a short-lived JWT using PEM from environment.
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
        raise ValueError("Missing COINBASE_PEM_KEY or COINBASE_PEM_KEY_B64 env variable")

    pem = _sanitize_and_normalize_pem(raw_pem, from_b64=from_b64)

    if "-----BEGIN" not in pem or "PRIVATE KEY" not in pem:
        raise ValueError(f"Normalized PEM does not contain expected header/trailer. First 100 chars: {pem[:100]}")

    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 min
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
    Returns a cached JWT, regenerates if expired.
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
# Debug helper: decode & log JWT payload
# -----------------------------
def debug_print_jwt_payload():
    try:
        token = get_jwt_token()
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=="  # pad if needed
            payload_json = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)).decode()
            logger.info("[NIJA-JWT-DEBUG] JWT payload: %s", payload_json)
    except Exception as e:
        logger.debug("[NIJA-JWT-DEBUG] Could not decode JWT payload: %s", e)
