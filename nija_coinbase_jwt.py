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


def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool = False) -> str:
    """
    Returns a properly formatted PEM string for Coinbase JWT.
    Handles:
      - full PEM pasted (multi-line)
      - single-line PEM with '\n'
      - base64 of just key body
      - base64 of full PEM
    """
    import re
    import base64
    pem = raw_pem.strip()

    if from_b64:
        # remove all whitespace/newlines
        b64_clean = re.sub(r"\s+", "", pem)
        # pad base64 if needed
        padded = b64_clean + "=" * (-len(b64_clean) % 4)
        # decode safely; do not decode as utf-8 yet
        try:
            decoded_bytes = base64.b64decode(padded)
        except Exception as e:
            raise ValueError(f"[NIJA-JWT] Failed to decode base64 PEM: {e}")

        # Check if decoded bytes already have PEM headers
        if b"BEGIN" in decoded_bytes and b"END" in decoded_bytes:
            pem = decoded_bytes.decode("utf-8")
        else:
            # It's just key body, wrap with header/trailer
            body = base64.b64encode(decoded_bytes).decode("ascii")
            # insert line breaks every 64 chars
            wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
            pem = f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"

    # If literal '\n' in raw PEM, convert to actual newline
    pem = pem.replace("\\n", "\n")

    # If headers present, ensure proper formatting
    if "-----BEGIN" in pem and "-----END" in pem:
        pem = pem.strip()
        if not pem.endswith("\n"):
            pem += "\n"
        return pem

    # Otherwise, treat as just body
    if re.fullmatch(r"[A-Za-z0-9+/=]+", pem):
        wrapped = "\n".join([pem[i:i+64] for i in range(0, len(pem), 64)])
        pem = f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"
        return pem

    raise ValueError("[NIJA-JWT] Could not normalize PEM. Check env variable formatting.")


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
