# nija_client.py
import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

load_dotenv()
logger.remove()
logger.add(lambda m: print(m, end=""), level="DEBUG")

BASE_URL = "https://api.coinbase.com"
CB_VERSION = os.environ.get("CB_VERSION", "2025-11-12")

def _normalize_pem(pem_raw: str) -> str:
    if not pem_raw:
        return ""
    pem = pem_raw.replace("\\n", "\n")
    if pem.startswith('"') and pem.endswith('"'):
        pem = pem[1:-1]
    return pem.strip()

def load_private_key(pem_raw: str = None, pem_path: str = None):
    pem_content = ""
    if pem_path:
        try:
            with open(pem_path, "r", encoding="utf-8") as f:
                pem_content = f.read()
            logger.info("Loaded PEM from path")
        except Exception as e:
            logger.warning("Failed to read PEM_PATH: %s", e)

    if not pem_content and pem_raw:
        pem_content = _normalize_pem(pem_raw)

    if not pem_content:
        logger.warning("PEM content not found")
        return None

    try:
        private_key = serialization.load_pem_private_key(
            pem_content.encode("utf-8"), password=None, backend=default_backend()
        )
        logger.info("Private key loaded")
        return private_key
    except Exception as e:
        logger.exception("Failed to load private key: %s", e)
        return None

class CoinbaseClient:
    def __init__(self, api_key_id=None, org_id=None, private_key=None):
        self.api_key_id = api_key_id
        self.org_id = org_id
        self.private_key = private_key
        self.base_url = BASE_URL + "/api/v3/brokerage"

        if not self.api_key_id:
            logger.error("COINBASE_API_KEY not provided")
        if not self.org_id:
            logger.error("COINBASE_ORG_ID not provided")
        if not self.private_key:
            logger.error("Private key not loaded")

    def _generate_jwt(self, method: str, request_path: str) -> str | None:
        if not self.private_key or not self.api_key_id:
            logger.error("Cannot generate JWT: missing private key or api_key_id")
            return None
        try:
            iat = int(time.time())
            payload = {
                "iat": iat,
                "exp": iat + 120,
                "sub": self.api_key_id,
                "request_path": request_path,
                "method": method.upper()
            }
            headers = {"alg": "ES256", "kid": self.api_key_id}
            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            logger.debug("DEBUG_JWT preview=%s", (token[:200] if token else None))
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def get_accounts(self):
        # Coinbase expects request_path to match the path included in JWT
        # e.g. "/api/v3/brokerage/organizations/<org_id>/accounts"
        api_path = f"/organizations/{self.org_id}/accounts"
        request_path = f"/api/v3/brokerage{api_path}"
        url = self.base_url + api_path

        token = self._generate_jwt("GET", request_path)
        if not token:
            logger.error("No JWT generated; skipping request")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "Content-Type": "application/json"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("HTTP %s: %s", resp.status_code, resp.text[:1000])
                return None
        except requests.RequestException as e:
            logger.exception("HTTP request failed: %s", e)
            return None
