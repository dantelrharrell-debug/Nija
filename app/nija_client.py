# nija_client.py
import os
import requests
import jwt
from loguru import logger
from datetime import datetime, timedelta

# Optional runtime validation using cryptography (installed by PyJWT deps)
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
    Supports:
     - COINBASE_JWT_PEM (raw PEM, can include literal \n sequences)
     - COINBASE_JWT_PEM_BASE64 (base64 encoded PEM blob)
    Falls back to API key auth when JWT PEM is missing/invalid.
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")
        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        # Load and normalize PEM (tries base64 env fallback too)
        self.pem_content = self._load_and_validate_pem()

        # Log mode selection (masked)
        if self.pem_content:
            logger.info("Advanced JWT auth enabled (PEM validated). kid=%s issuer=%s", _mask(self.kid,10), _mask(self.issuer,10))
        else:
            logger.warning("JWT PEM not usable — falling back to API-key auth. Ensure COINBASE_JWT_PEM or COINBASE_JWT_PEM_BASE64 is set and valid.")

        # Basic credential presence check
        if not self.api_key or not self.api_secret:
            logger.error("Coinbase API key or secret missing.")
            raise ValueError("Missing Coinbase credentials")

        logger.info("CoinbaseClient initialized. base=%s", self.base_url)

    def _load_and_validate_pem(self):
        """
        Attempts to load PEM from:
         1) COINBASE_JWT_PEM (raw or with \\n)
         2) COINBASE_JWT_PEM_BASE64 (base64 encoded PEM)
        Performs normalization and validation (if cryptography available).
        Returns the normalized PEM string or None.
        """
        raw = os.getenv("COINBASE_JWT_PEM", "").strip()
        b64 = os.getenv("COINBASE_JWT_PEM_BASE64", "").strip()

        # If base64 env present, decode first (this is safe for web GUIs)
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
            # Normalize common paste mistakes:
            # - User pasted with literal "\n" characters, convert them to newlines
            # - Replace escaped CRLFs
            pem_candidate = raw.replace("\\r\\n", "\n").replace("\\n", "\n")
            # If user pasted without BEGIN/END but it's a base64 block, attempt to detect later
            logger.debug("COINBASE_JWT_PEM provided, length=%d (first50)=%s", len(pem_candidate), _mask(pem_candidate,50))
        else:
            logger.debug("No PEM env provided")
            return None

        # Trim and attempt to ensure BEGIN/END present; if not present, do not auto-invent,
        # but attempt to wrap if it looks like base64 (very long and only base64 chars)
        pc = pem_candidate.strip()
        if not pc.startswith("-----BEGIN"):
            # detect if looks like base64 block (alpha numeric + / + + and =)
            import re
            if re.fullmatch(r"[A-Za-z0-9+/=\s]+", pc) and len(pc) > 200:
                logger.info("PEM appears to be base64 without headers; attempting to wrap with BEGIN/END.")
                pc = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(pc[i:i+64] for i in range(0, len(pc), 64)) + "\n-----END PRIVATE KEY-----\n"
            else:
                logger.warning("PEM present but does not look well-formed (missing BEGIN/END).")
                # continue to try validation in case it contains BEGIN later
        # Ensure canonical newlines
        pc = pc.replace("\r\n", "\n").replace("\r", "\n")

        # Validate using cryptography if available
        if HAS_CRYPTO:
            try:
                key_bytes = pc.encode("utf-8")
                # load_pem_private_key will raise if malformed or encrypted (passworded)
                load_pem_private_key(key_bytes, password=None, backend=default_backend())
                logger.debug("PEM validation via cryptography succeeded.")
                return pc
            except Exception as e:
                logger.error("PEM validation failed: %s", e)
                # final fallback: return None to disable JWT path
                return None
        else:
            # cryptography not available; do a best-effort check for BEGIN/END
            if "-----BEGIN" in pc and "-----END" in pc:
                logger.warning("cryptography not available; assuming PEM is OK (not validated). Consider installing cryptography.")
                return pc
            logger.error("PEM not validated and cryptography not available.")
            return None

    def _get_jwt(self):
        if not self.pem_content:
            return None
        if not (self.kid and self.issuer and self.org_id):
            logger.error("JWT fields missing: kid/issuer/org_id. Cannot generate JWT.")
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
            # PyJWT may return bytes or str depending on version
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

    # Example public method
    def get_accounts(self):
        return self._request("GET", "/accounts")
