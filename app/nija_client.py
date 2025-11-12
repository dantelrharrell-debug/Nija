# nija_client.py
import os
import requests
import jwt
from loguru import logger
from datetime import datetime, timedelta

try:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False

def _mask(s, keep=10):
    if not s:
        return "<empty>"
    if len(s) <= keep:
        return s[:3] + "..."
    return s[:keep] + "...(masked)"

class CoinbaseClient:
    """
    Robust Coinbase client with PEM normalization & validation.
    Uses JWT (COINBASE_JWT_PEM or COINBASE_JWT_PEM_BASE64) if valid,
    otherwise falls back to API key auth (COINBASE_API_KEY / COINBASE_API_SECRET).
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY", "").strip()
        self.api_secret = os.getenv("COINBASE_API_SECRET", "").strip()
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com").strip()
        self.kid = os.getenv("COINBASE_JWT_KID", "").strip()
        self.issuer = os.getenv("COINBASE_JWT_ISSUER", "").strip()
        self.org_id = os.getenv("COINBASE_ORG_ID", "").strip()

        # Load PEM (raw or base64)
        self.pem_content = self._load_and_validate_pem()

        if self.pem_content:
            logger.info("Advanced JWT auth enabled (PEM validated). kid=%s issuer=%s",
                        _mask(self.kid, 10), _mask(self.issuer, 10))
        else:
            logger.warning("JWT PEM not usable — will use API-key auth if API keys present.")

        if not (self.api_key and self.api_secret):
            logger.error("Coinbase API key or secret missing.")
            raise ValueError("Missing Coinbase credentials")

        logger.info("CoinbaseClient initialized. base=%s", self.base_url)

    def _load_and_validate_pem(self):
        raw = os.getenv("COINBASE_JWT_PEM", "").strip()
        b64 = os.getenv("COINBASE_JWT_PEM_BASE64", "").strip()

        pem_candidate = None

        if b64:
            try:
                import base64
                decoded = base64.b64decode(b64)
                pem_candidate = decoded.decode("utf-8", errors="ignore")
                logger.debug("COINBASE_JWT_PEM_BASE64 provided, decoded length=%d", len(pem_candidate))
            except Exception as e:
                logger.warning("COINBASE_JWT_PEM_BASE64 decode failed: %s", e)
                pem_candidate = None
        elif raw:
            pem_candidate = raw.replace("\\r\\n", "\n").replace("\\n", "\n")
            logger.debug("COINBASE_JWT_PEM provided, length=%d", len(pem_candidate))
        else:
            return None

        if not pem_candidate:
            return None

        pc = pem_candidate.strip()
        # If it looks like raw base64 (no BEGIN), try wrapping
        if not pc.startswith("-----BEGIN"):
            import re
            if re.fullmatch(r"[A-Za-z0-9+/=\s]+", pc) and len(pc) > 200:
                logger.info("PEM appears to be base64 without headers; wrapping with BEGIN/END.")
                pc = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(pc[i:i+64] for i in range(0, len(pc), 64)) + "\n-----END PRIVATE KEY-----\n"
            else:
                logger.warning("PEM present but does not look well-formed (missing BEGIN/END).")

        pc = pc.replace("\r\n", "\n").replace("\r", "\n")

        if HAS_CRYPTO:
            try:
                load_pem_private_key(pc.encode("utf-8"), password=None, backend=default_backend())
                logger.debug("PEM validation via cryptography succeeded.")
                return pc
            except Exception as e:
                logger.error("PEM validation failed: %s", e)
                return None
        else:
            if "-----BEGIN" in pc and "-----END" in pc:
                logger.warning("cryptography not available; assuming PEM OK (not validated).")
                return pc
            logger.error("PEM not validated and cryptography not available.")
            return None

    def _get_jwt(self):
        if not self.pem_content:
            return None
        if not (self.kid and self.issuer and self.org_id):
            logger.error("Missing JWT configuration (kid/issuer/org_id).")
            return None

        payload = {
            "iss": self.issuer,
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(seconds=60)).timestamp()),
            "sub": self.org_id,
        }
        headers = {"kid": self.kid}
        try:
            token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers=headers)
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            return token
        except Exception as e:
            logger.error("Failed to generate JWT: %s", e)
            return None

    def _headers(self):
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2025-11-01",
            "Content-Type": "application/json",
        }
        token = self._get_jwt()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        headers = self._headers()
        try:
            r = requests.request(method, url, headers=headers, json=data, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("HTTP request failed for %s: %s", endpoint, e)
            raise

    def get_accounts(self):
        return self._request("GET", "/accounts")
