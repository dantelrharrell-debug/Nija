# /app/main.py
import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Load .env (safe for local/dev)
load_dotenv()

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="DEBUG")

# --- Config (env names)
API_KEY_ID = os.environ.get("COINBASE_API_KEY") or os.environ.get("COINBASE_API_KEY_ID") or os.environ.get("COINBASE_KID")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM", "")            # full PEM or escaped \n string
PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "")      # optional filesystem path
BASE_URL = "https://api.coinbase.com"
CB_VERSION = os.environ.get("CB_VERSION", "2025-11-12")

def _normalize_pem(pem_raw: str) -> str:
    if not pem_raw:
        return ""
    pem = pem_raw.replace("\\n", "\n")
    if pem.startswith('"') and pem.endswith('"'):
        pem = pem[1:-1]
    return pem.strip()

def load_private_key():
    pem_content = ""
    # try path first
    if PEM_PATH:
        try:
            with open(PEM_PATH, "r", encoding="utf-8") as f:
                pem_content = f.read()
            logger.info("Loaded PEM from COINBASE_PEM_PATH")
        except Exception as e:
            logger.warning("Failed to read COINBASE_PEM_PATH (%s): %s", PEM_PATH, e)

    if not pem_content and PEM_RAW:
        pem_content = _normalize_pem(PEM_RAW)

    if not pem_content:
        logger.warning("No PEM content found in COINBASE_PEM or COINBASE_PEM_PATH")
        return None

    try:
        private_key = serialization.load_pem_private_key(
            pem_content.encode("utf-8"), password=None, backend=default_backend()
        )
        logger.info("Private key loaded successfully")
        return private_key
    except Exception as e:
        logger.exception("Failed to load private key: %s", e)
        return None

class CoinbaseClient:
    def __init__(self, api_key_id: str | None, org_id: str | None, private_key):
        self.api_key_id = api_key_id
        self.org_id = org_id
        self.private_key = private_key
        # base_url for brokerage endpoints in your logs
        self.base_url = BASE_URL + "/api/v3/brokerage"

        if not self.api_key_id or not self.org_id:
            logger.error("Missing COINBASE_API_KEY or COINBASE_ORG_ID (api_key_id=%s org_id=%s)",
                         bool(self.api_key_id), bool(self.org_id))
        if not self.private_key:
            logger.error("Private key not loaded; COINBASE_PEM is missing/invalid")

    def _generate_jwt(self, method: str, request_path: str) -> str | None:
        if not self.private_key or not self.api_key_id:
            logger.error("Cannot generate JWT: private key or api_key_id missing")
            return None
        try:
            iat = int(time.time())
            payload = {
                "iat": iat,
                "exp": iat + 120,                    # 2 minute expiry
                "sub": self.api_key_id,              # must be API key id
                "request_path": request_path,        # exact path Coinbase expects
                "method": method.upper(),
            }
            headers = {"alg": "ES256", "kid": self.api_key_id}
            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            logger.debug("DEBUG_JWT: token_preview=%s", (token[:200] if token else None))
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def get_accounts(self):
        # path used in your previous logs & matched to request_path in JWT
        path = f"/organizations/{self.org_id}/accounts"
        request_path = f"/api/v3/brokerage{path}"
        url = self.base_url + path

        token = self._generate_jwt("GET", request_path)
        if not token:
            logger.error("Skipping accounts request because JWT not available")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.debug("Accounts fetched OK")
                return resp.json()
            else:
                # include response text truncated
                logger.error("HTTP %s: %s", resp.status_code, resp.text[:500])
                return None
        except requests.exceptions.RequestException as e:
            logger.exception("Request error in get_accounts: %s", e)
            return None

# -------------------------
# Script entry
# -------------------------
def start_bot_main():
    logger.info("Nija bot starting...")

    private_key = load_private_key()
    client = CoinbaseClient(API_KEY_ID, ORG_ID, private_key)

    # initial attempt
    accounts = client.get_accounts()
    if accounts:
        logger.info("Startup accounts fetch succeeded")
    else:
        logger.warning("Startup accounts fetch failed (see logs). We'll continue running and retry.")

    # heartbeat loop (safe, will not crash)
    try:
        while True:
            accounts = client.get_accounts()
            if accounts:
                logger.info("Heartbeat: accounts OK")
            else:
                logger.warning("Heartbeat: accounts fetch failed")
            logger.info("heartbeat")
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Unexpected runtime error: %s", e)

if __name__ == "__main__":
    start_bot_main()
