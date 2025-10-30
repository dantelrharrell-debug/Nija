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
    # crude check: mostly base64 chars and length reasonable
    import re
    if not s:
        return False
    s_clean = s.strip()
    # remove possible whitespace/newlines for check
    s_compact = re.sub(r"\s+", "", s_clean)
    # base64 regex (allow padding =)
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", s_compact)) and (len(s_compact) % 4 == 0 or len(s_compact) > 40)

def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool=False) -> str:
    """
    Return a well-formed PEM string. Handles these cases:
      - Full PEM pasted with BEGIN/END (multi-line)
      - Single-line with literal '\n' sequences
      - Only base64 body (will be wrapped into BEGIN/END)
      - base64-encoded full PEM passed in (from_b64=True), decoded then sanitized
    """
    if raw_pem is None:
        raise ValueError("No PEM provided in environment")

    pem = raw_pem.strip()

    # If it's base64-encoded full PEM (we were told from_b64), decode it to text
    if from_b64:
        try:
            pem = base64.b64decode(pem).decode("utf-8")
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to decode COINBASE_PEM_KEY_B64: %s", e)
            raise

    # If the user pasted a string with literal backslash-n sequences, convert them
    if "\\n" in pem and "BEGIN" in pem and "END" in pem:
        pem = pem.replace("\\n", "\n")

    # Strip surrounding quotes if present
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1].strip()

    # If PEM already contains headers, normalize spacing/newlines
    if "-----BEGIN" in pem and "-----END" in pem:
        # ensure header/trailer on own lines and end with newline
        pem = pem.strip()
        if not pem.endswith("\n"):
            pem = pem + "\n"
        return pem

    # If we reach here and the string looks like base64 body, wrap it
    # (handles the case where user pasted only the 'MHcCAQEEIOrZ...' piece)
    if _looks_like_base64(pem):
        logger.info("[NIJA-JWT] Detected base64 PEM body; wrapping with BEGIN/END headers")
        # Insert line breaks every 64 chars for PEM readability (not strictly required)
        body = "".join(pem.split())
        wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        pem_full = "-----BEGIN EC PRIVATE KEY-----\n" + wrapped + "\n-----END EC PRIVATE KEY-----\n"
        return pem_full

    # Otherwise, if it's neither headered PEM nor base64 body, return as-is and let jwt fail with clear message
    return pem

def _build_jwt():
    """
    Build a short-lived JWT signed with the PEM key provided in env.
    Accepts either COINBASE_PEM_KEY (raw or base64-body or 'escaped \\n') or COINBASE_PEM_KEY_B64 (base64-of-full-pem).
    """
    # Priority: COINBASE_PEM_KEY_B64 (base64 of full PEM) > COINBASE_PEM_KEY (raw) 
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

    # very small sanity check
    if "-----BEGIN" not in pem or "PRIVATE KEY" not in pem:
        logger.error("[NIJA-JWT] PEM does not appear valid after normalization. First 100 chars: %s", pem[:100])
        raise ValueError("Normalized PEM does not contain expected header/trailer")

    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,   # 5 minutes
        "sub": ORG_ID,
        "kid": KEY_ID
    }

    try:
        token = jwt.encode(payload, pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode()
        return token, payload["exp"]
    except Exception as e:
        # Bubble up with explicit guidance
        logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
        logger.error("[NIJA-JWT] Common causes: PEM formatting lost linebreaks, PEM is corrupted, or key is not a private key.")
        logger.error("[NIJA-JWT] Tips: set COINBASE_PEM_KEY to full multi-line PEM, or set COINBASE_PEM_KEY_B64 to base64 of full PEM via an encoder site.")
        raise

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
            logger.error("[NIJA-JWT] Unable to create JWT: %s", e)
            raise
