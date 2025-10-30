# nija_coinbase_jwt.py
import os
import time
import jwt
import logging
from threading import Lock

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

# Read env
_RAW_PEM = os.environ.get("COINBASE_PEM_KEY", None)
KEY_ID = os.environ.get("COINBASE_API_KEY_ID", None)
ORG_ID = os.environ.get("COINBASE_ORG_ID", None)

if not (KEY_ID and ORG_ID):
    logger.warning("[NIJA-JWT] COINBASE_API_KEY_ID or COINBASE_ORG_ID missing from env. JWT generation will fail until they are set.")

_TOKEN_CACHE = {"token": None, "exp": 0}
_LOCK = Lock()

def _sanitize_pem(raw_pem: str) -> str:
    """
    Make common PEM encoding mistakes safe:
     - If the PEM was stored as a single-line with literal '\n', replace them with real newlines.
     - Remove surrounding quotes, leading/trailing whitespace.
     - Ensure BEGIN/END header exists.
    """
    if raw_pem is None:
        raise ValueError("No PEM provided in COINBASE_PEM_KEY")

    pem = raw_pem.strip()

    # If user pasted the PEM with literal backslash-n sequences (common in web UIs),
    # convert them into actual newlines.
    if "\\n" in pem and "BEGIN" in pem and "END" in pem:
        pem = pem.replace("\\n", "\n")

    # If PEM appears to be base64 or single-line without BEGIN header, leave as-is
    # but still try to detect and correct common issues.
    # Remove wrapping quotes if someone pasted with surrounding quotes.
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1].strip()

    # Ensure proper newlines around headers
    if "-----BEGIN" in pem and "-----END" in pem:
        # Guarantee header/trailer are on their own lines
        pem = pem.replace("-----BEGIN", "\n-----BEGIN")
        pem = pem.replace("-----END", "\n-----END")
        pem = pem.strip() + "\n"
    else:
        # If header missing, still return pem and let jwt/cryptography raise a clearer error
        pass

    return pem

def _build_jwt():
    """
    Build a short-lived JWT signed with the PEM key provided in env.
    """
    raw_pem = _RAW_PEM
    if not raw_pem:
        raise ValueError("COINBASE_PEM_KEY environment variable is missing. Provide your PEM key in COINBASE_PEM_KEY.")

    try:
        pem = _sanitize_pem(raw_pem)
    except Exception as e:
        logger.error("[NIJA-JWT] PEM sanitization failed: %s", e)
        raise

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
        # Provide very explicit guidance in logs for this common error
        logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
        logger.error("[NIJA-JWT] Common causes: PEM formatting lost linebreaks, PEM is corrupted, or key is not the PEM private key.")
        logger.error("[NIJA-JWT] If PEM looks like a single line containing '\\n', update COINBASE_PEM_KEY so newlines are real, or let the service store multiline env values.")
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
