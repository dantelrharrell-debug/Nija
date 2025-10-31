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

# --- Coinbase API credentials ---
KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not (KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_API_KEY_ID or COINBASE_ORG_ID missing from env. JWT generation will fail until they are set.")

# --- Cached token ---
_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()


def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool = False) -> str:
    """
    Returns a properly formatted PEM string for Coinbase JWT.
    Handles:
      - full multi-line PEM
      - single-line PEM with literal '\n'
      - base64 of just key body
      - base64 of full PEM
    """
    pem = raw_pem.strip()
    pem = pem.replace("\\n", "\n")  # literal \n -> newline

    if from_b64:
        b64_clean = re.sub(r"\s+", "", pem)
        padded = b64_clean + "=" * (-len(b64_clean) % 4)
        try:
            decoded_bytes = base64.b64decode(padded)
        except Exception as e:
            raise ValueError(f"[NIJA-JWT] Failed to decode base64 PEM: {e}")

        if b"BEGIN" in decoded_bytes and b"END" in decoded_bytes:
            pem = decoded_bytes.decode("utf-8")
        else:
            body = base64.b64encode(decoded_bytes).decode("ascii")
            wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
            pem = f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"

    if "-----BEGIN" in pem and "-----END" in pem:
        lines = [line.strip() for line in pem.strip().splitlines() if line.strip()]
        header = lines[0]
        footer = lines[-1]
        body = "\n".join(lines[1:-1]).replace("\n", "")
        wrapped_body = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        pem = f"{header}\n{wrapped_body}\n{footer}\n"
        return pem

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
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode()
            logger.info("[NIJA-JWT-DEBUG] JWT payload: %s", payload_json)
    except Exception as e:
        logger.debug("[NIJA-JWT-DEBUG] Could not decode JWT payload: %s", e)
