# /app/nija_client.py
import os, time, base64
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda m: print(m, end=""))

API_KEY = os.environ.get("COINBASE_API_KEY", "")
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
# Prefer base64 env to avoid newline issues in providers
PEM_B64 = os.environ.get("COINBASE_PEM_B64", "").strip()
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT", "").strip()

def try_load_private_key_from_bytes(b: bytes):
    try:
        priv = serialization.load_pem_private_key(b, password=None, backend=default_backend())
        logger.info("✅ loaded PEM private key (bytes).")
        return priv
    except Exception as e:
        logger.debug(f"load_pem_private_key bytes failed: {type(e).__name__}: {e}")
        return None

def try_load_private_key_from_text(text: str):
    # Normalize escaped newlines if someone stored literal "\n"
    if "\\n" in text:
        text = text.replace("\\n", "\n")
    b = text.encode()
    return try_load_private_key_from_bytes(b)

def load_private_key():
    # 1) try base64 (preferred)
    if PEM_B64:
        try:
            logger.info("Attempting to decode COINBASE_PEM_B64...")
            b = base64.b64decode(PEM_B64)
            k = try_load_private_key_from_bytes(b)
            if k:
                return k
            # sometimes the b64 encoded string was of the textual PEM (i.e. contains \n escapes)
            try:
                txt = b.decode(errors="ignore")
                return try_load_private_key_from_text(txt)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"COINBASE_PEM_B64 decode failed: {e}")

    # 2) try raw content stored in COINBASE_PEM_CONTENT
    if PEM_CONTENT:
        logger.info("Attempting to load COINBASE_PEM_CONTENT...")
        k = try_load_private_key_from_text(PEM_CONTENT)
        if k:
            return k

    # 3) try environment variable where newlines preserved (rare)
    env_direct = os.environ.get("COINBASE_PEM", "")
    if env_direct:
        logger.info("Attempting to load COINBASE_PEM (fallback)...")
        k = try_load_private_key_from_text(env_direct)
        if k:
            return k

    raise ValueError("No valid PEM loaded. Provide COINBASE_PEM_B64 or COINBASE_PEM_CONTENT correctly.")

class CoinbaseClient:
    def __init__(self):
        self.api_key = API_KEY
        self.org_id = ORG_ID
        self.base_url = "https://api.coinbase.com"
        if not self.api_key or not self.org_id:
            logger.warning("COINBASE_API_KEY or COINBASE_ORG_ID missing - make sure API key is full resource path or set ORG_ID.")
        # load private key
        self.priv = load_private_key()

    def generate_jwt(self):
        now = int(time.time())
        payload = {"iat": now, "exp": now + 300, "sub": self.api_key, "org_id": self.org_id}
        try:
            token = jwt.encode(payload, self.priv, algorithm="ES256")
            return token
        except Exception as e:
            logger.error(f"JWT generation failed: {type(e).__name__}: {e}")
            return None

    def make_request(self, method, endpoint, **kwargs):
        token = self.generate_jwt()
        if not token:
            logger.error("No JWT - aborting request.")
            return None
        headers = kwargs.pop("headers", {})
        headers.update({"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-14"})
        url = f"{self.base_url}{endpoint}"
        try:
            r = requests.request(method, url, headers=headers, **kwargs)
            if r.status_code >= 400:
                logger.error(f"Coinbase API returned {r.status_code}: {r.text}")
            return r
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            return None

# quick test when run directly (logs visible in Render)
if __name__ == "__main__":
    try:
        c = CoinbaseClient()
        resp = c.make_request("GET", "/v2/accounts")
        if resp:
            logger.info("Response status: " + str(resp.status_code))
            try:
                logger.info(resp.json())
            except Exception:
                logger.info(resp.text)
    except Exception as e:
        logger.error(f"Startup failed: {type(e).__name__}: {e}")
