import os, time, base64, re, logging
from threading import Lock
import jwt

logger = logging.getLogger("nija_coinbase_jwt")
logger.setLevel(logging.INFO)

KEY_ID = os.environ.get("COINBASE_API_KEY_ID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
_LOCK = Lock()
_TOKEN_CACHE = {"token": None, "exp": 0}

def _try_decode_utf8(b: bytes):
    try: return b.decode("utf-8")
    except: 
        try: return b.decode("latin-1")
        except: return None

def _normalize_pem_from_text(raw: str) -> str:
    if not raw: raise ValueError("Empty PEM input")
    if "\\n" in raw and "BEGIN" in raw: raw = raw.replace("\\n", "\n")
    raw = raw.strip()
    if "-----BEGIN" in raw and "-----END" in raw:
        if not raw.endswith("\n"): raw += "\n"
        return raw
    body = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"[A-Za-z0-9+/=]+", body):
        wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        return f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"
    raise ValueError("PEM input not recognized.")

def _load_pem():
    pem_text = os.environ.get("COINBASE_PEM_KEY")
    pem_b64 = os.environ.get("COINBASE_PEM_KEY_B64")
    if pem_b64:
        s = re.sub(r"\s+", "", pem_b64); s += "=" * (-len(s) % 4)
        try:
            decoded = base64.b64decode(s)
        except Exception as e:
            raise ValueError(f"Failed to decode COINBASE_PEM_KEY_B64: {e}")
        decoded_text = _try_decode_utf8(decoded)
        if decoded_text and ("-----BEGIN" in decoded_text): return _normalize_pem_from_text(decoded_text)
        b64body = base64.b64encode(decoded).decode("ascii")
        wrapped = "\n".join([b64body[i:i+64] for i in range(0, len(b64body), 64)])
        return f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"
    if pem_text: return _normalize_pem_from_text(pem_text)
    raise ValueError("Missing COINBASE_PEM_KEY or COINBASE_PEM_KEY_B64 env var")

def _build_jwt():
    if not KEY_ID or not ORG_ID:
        raise ValueError("Missing COINBASE_API_KEY_ID or COINBASE_ORG_ID")
    pem = _load_pem()
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "sub": ORG_ID, "kid": KEY_ID}
    try:
        token = jwt.encode(payload, pem, algorithm="ES256")
        if isinstance(token, bytes): token = token.decode()
        return token, payload["exp"]
    except Exception as e:
        logger.error("[NIJA-JWT] Failed to generate JWT: %s", e)
        raise

def get_jwt_token():
    with _LOCK:
        now = int(time.time())
        if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] - 10 > now:
            return _TOKEN_CACHE["token"]
        token, exp = _build_jwt()
        _TOKEN_CACHE["token"] = token; _TOKEN_CACHE["exp"] = exp
        logger.info("[NIJA-JWT] Generated new JWT (exp=%s)", exp)
        return token

def debug_print_jwt_payload():
    try:
        token = get_jwt_token()
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            logger.info("[NIJA-JWT-DEBUG] JWT payload: %s", payload_json)
    except Exception as e:
        logger.debug("[NIJA-JWT-DEBUG] Could not decode JWT payload: %s", e)
