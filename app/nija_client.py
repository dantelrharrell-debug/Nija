# app/nija_client.py
import os
import time
import json
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Load local .env if present (safe for dev editors)
load_dotenv()

# Config names (support multiple env styles)
API_KEY_ID = os.environ.get("COINBASE_API_KEY") or os.environ.get("COINBASE_API_KEY_ID") or os.environ.get("COINBASE_KID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
# Accept either full PEM in COINBASE_PEM (with real newlines or escaped \n), or a path to a file
PEM_RAW = os.environ.get("COINBASE_PEM", "")  # may contain escaped \n
PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "")

BASE_URL = "https://api.coinbase.com"

def _normalize_pem(pem_raw: str) -> str:
    """Convert possible escaped newlines into real newlines and ensure wrapping."""
    if not pem_raw:
        return ""
    # If someone pasted with literal \n, convert them
    pem = pem_raw.replace("\\n", "\n")
    # Trim accidental surrounding quotes
    if pem.startswith('"') and pem.endswith('"'):
        pem = pem[1:-1]
    return pem

class CoinbaseClient:
    def __init__(self):
        self.api_key_id = API_KEY_ID
        self.org_id = ORG_ID
        self.base_url = BASE_URL + "/api/v3/brokerage"  # match your previous paths

        self.private_key = None
        pem_content = ""

        # Try load PEM from path if provided
        if PEM_PATH:
            try:
                with open(PEM_PATH, "r", encoding="utf-8") as f:
                    pem_content = f.read()
                logger.info("Loaded PEM from COINBASE_PEM_PATH")
            except Exception as e:
                logger.warning("Failed to load PEM_PATH '%s': %s", PEM_PATH, e)

        # Otherwise try raw env
        if not pem_content and PEM_RAW:
            pem_content = _normalize_pem(PEM_RAW)

        # Attempt to load private key if we have content
        if pem_content:
            try:
                self.private_key = serialization.load_pem_private_key(
                    pem_content.encode("utf-8"), password=None, backend=default_backend()
                )
                logger.info("Private key loaded successfully")
            except Exception as e:
                logger.exception("Failed to load private key: %s", e)
                self.private_key = None
        else:
            logger.warning("No PEM content found in COINBASE_PEM or COINBASE_PEM_PATH")

        if not self.api_key_id or not self.org_id or not self.private_key:
            # We *do not* crash here — we log and allow the app to run in "disconnected" mode.
            logger.error("Missing or invalid Coinbase credentials. "
                         "COINBASE_API_KEY=%s COINBASE_ORG_ID=%s private_key_loaded=%s",
                         bool(self.api_key_id), bool(self.org_id), bool(self.private_key))

    def _generate_jwt(self, method: str, request_path: str) -> str | None:
        """Generate JWT per Coinbase Advanced API requirements. Return None on failure."""
        if not self.private_key or not self.api_key_id:
            logger.error("Cannot generate JWT: missing private key or api_key_id")
            return None

        try:
            iat = int(time.time())
            payload = {
                "iat": iat,
                "exp": iat + 120,  # 2 minute expiry
                "sub": self.api_key_id,
                "request_path": request_path,
                "method": method.upper()
            }
            headers = {"alg": "ES256", "kid": self.api_key_id}
            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            # Small debug info (safe) - do not log the full private key
            logger.debug("DEBUG_JWT: token_preview=%s", token[:200])
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def get_accounts(self):
        """
        Fetch organizations/<org>/accounts
        Safe: returns None on failure instead of raising.
        """
        path = f"/organizations/{self.org_id}/accounts"
        request_path = f"/api/v3/brokerage{path}"
        url = self.base_url + path  # base_url already contains /api/v3/brokerage

        token = self._generate_jwt("GET", request_path)
        if not token:
            logger.error("Skipping accounts request: JWT not available")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-12",
            "Content-Type": "application/json"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("HTTP %s: %s", resp.status_code, resp.text[:500])
                return None
        except requests.exceptions.RequestException as e:
            logger.exception("RequestException in get_accounts: %s", e)
            return None
