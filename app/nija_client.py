# nija_client.py
import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from typing import Optional, Any

logger.configure(level=os.environ.get("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Minimal Coinbase Advanced (Brokerage) JWT-auth client.
    Expects either:
      - COINBASE_PEM_PATH -> path to PEM file on disk, OR
      - COINBASE_PEM -> PEM text (with real newlines, not escaped)
    And:
      - COINBASE_API_KEY (the API key id / kid)
      - COINBASE_ORG_ID
    """
    def __init__(self,
                 api_key: Optional[str] = None,
                 org_id: Optional[str] = None,
                 private_key=None):
        # prefer explicit args, else environment
        self.api_key_id = api_key or os.environ.get("COINBASE_API_KEY")
        self.org_id = org_id or os.environ.get("COINBASE_ORG_ID")
        self.base_url = "https://api.coinbase.com"
        self.brokerage_base = f"{self.base_url}/api/v3/brokerage"

        # load private key object if passed in; else load from env/path
        if private_key:
            self.private_key = private_key
        else:
            self.private_key = self._load_private_key_from_env()

        if not self.api_key_id or not self.org_id or not self.private_key:
            logger.error("Missing Coinbase credentials: API key, ORG ID, or PEM private key")
            # don't raise here — caller can handle; but many operations will fail
        else:
            logger.info("CoinbaseClient initialized (org_id=%s)", self.org_id)

    def _load_private_key_from_env(self):
        """
        Load PEM from COINBASE_PEM_PATH or COINBASE_PEM.
        Returns a cryptography private key object or None.
        """
        pem_path = os.environ.get("COINBASE_PEM_PATH")
        pem_text = os.environ.get("COINBASE_PEM")
        raw = None

        try:
            if pem_path:
                logger.debug("Loading PEM from path: %s", pem_path)
                with open(pem_path, "rb") as f:
                    raw = f.read()
            elif pem_text:
                # If environment stores escaped newlines, convert them
                pem_fixed = pem_text.replace("\\n", "\n")
                raw = pem_fixed.encode()
            else:
                logger.warning("COINBASE_PEM_PATH and COINBASE_PEM not set")
                return None

            pk = serialization.load_pem_private_key(raw, password=None, backend=default_backend())
            logger.info("Private key loaded successfully")
            return pk
        except Exception as e:
            logger.exception("Failed to load private key: %s", e)
            return None

    def _generate_jwt(self, request_path: str, method: str = "GET") -> Optional[str]:
        """
        Generate a JWT for Coinbase Advanced API.
        request_path: the exact path expected by Coinbase, e.g. '/api/v3/brokerage/organizations/.../accounts'
        method: uppercase HTTP method
        """
        if not self.private_key or not self.api_key_id:
            logger.error("Cannot generate JWT: missing private key or api key id")
            return None

        try:
            iat = int(time.time())
            payload = {
                "iat": iat,
                "exp": iat + 120,               # short lived
                "sub": self.api_key_id,
                "request_path": request_path,
                "method": method.upper()
            }
            # header must include kid per Coinbase docs
            headers = {"alg": "ES256", "kid": self.api_key_id}

            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            # token may be bytes or str depending on PyJWT version
            if isinstance(token, bytes):
                token = token.decode()
            # Debug preview only when enabled
            if os.environ.get("DEBUG_JWT") == "1":
                logger.info("DEBUG_JWT token_preview=%s", token[:200])
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def get_accounts(self) -> Optional[Any]:
        """
        Fetch accounts for organization.
        """
        path = f"/api/v3/brokerage/organizations/{self.org_id}/accounts"
        token = self._generate_jwt(path, "GET")
        if not token:
            logger.error("No JWT token; aborting get_accounts")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": os.environ.get("CB_VERSION", "2025-11-12"),
            "Accept": "application/json"
        }
        url = self.brokerage_base + f"/organizations/{self.org_id}/accounts"  # keep same shape
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if os.environ.get("DEBUG_JWT") == "1":
                logger.info("DEBUG_JWT: HTTP %s response_text(500)=%s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            # include response text safely in logs
            txt = getattr(e.response, "text", "<no-response-text>")
            logger.error("HTTP error fetching accounts: %s | Response: %s", e, txt)
            return None
        except Exception as e:
            logger.exception("Error fetching accounts: %s", e)
            return None

    # you can add more functions like place_order() using same pattern
