# /app/nija_hmac_client.py
"""
Defensive Coinbase HMAC / Advanced client.
- Tries Advanced (JWT) if PEM + COINBASE_ISS provided and pyjwt available.
- Falls back to Retail HMAC (CB-ACCESS-SIGN) if Advanced not configured.
- Safe JSON parsing (no crash on non-JSON).
- Provides: CoinbaseClient.request(method, path, data=None) -> (status, data_or_text)
           CoinbaseClient.get_accounts() -> (status, data_or_text)
"""

import os
import time
import hmac
import hashlib
import base64
import json
import logging
from typing import Tuple

import requests

logger = logging.getLogger("nija_hmac_client")
logging.basicConfig(level=logging.INFO)

# envs
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "").rstrip("/")  # may be blank
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")
COINBASE_ISS = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ISSUER")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")

# sensible defaults
CDP_BASE = "https://api.cdp.coinbase.com"
RETAIL_BASE = "https://api.coinbase.com"
if not COINBASE_API_BASE:
    # if we have Advanced creds assume CDP, otherwise retail
    COINBASE_API_BASE = CDP_BASE if COINBASE_ISS or COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH else RETAIL_BASE

# helper: write PEM if PEM content provided
def ensure_pem_file() -> str | None:
    if COINBASE_PEM_CONTENT:
        path = COINBASE_PRIVATE_KEY_PATH or "/app/coinbase_advanced.pem"
        try:
            os.makedirs(os.path.dirname(path) or "/app", exist_ok=True)
            with open(path, "w") as f:
                f.write(COINBASE_PEM_CONTENT)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
            logger.info(f"[nija_hmac_client] PEM content written to {path}")
            return path
        except Exception as e:
            logger.exception(f"[nija_hmac_client] Failed to write PEM: {e}")
            return None
    if COINBASE_PRIVATE_KEY_PATH and os.path.exists(COINBASE_PRIVATE_KEY_PATH):
        return COINBASE_PRIVATE_KEY_PATH
    return None

# JWT generation (advanced). Use pyjwt if available.
def generate_jwt_with_pem(pem_path: str, issuer: str, ttl_seconds: int = 30) -> str | None:
    try:
        import jwt  # pyjwt
    except Exception:
        logger.warning("[nija_hmac_client] pyjwt not installed; cannot generate JWT automatically.")
        return None

    try:
        now = int(time.time())
        payload = {
            "iss": issuer,
            "iat": now,
            "exp": now + ttl_seconds,
        }
        # ES256 with ECDSA PEM
        token = jwt.encode(payload, open(pem_path, "rb").read(), algorithm="ES256")
        logger.debug("[nija_hmac_client] JWT generated (short-lived).")
        return token
    except Exception as e:
        logger.exception(f"[nija_hmac_client] Error generating JWT: {e}")
        return None

class CoinbaseClient:
    def __init__(self, base: str | None = None, advanced: bool | None = None):
        # allow pass-in override
        self.base = (base or COINBASE_API_BASE).rstrip("/")
        self.api_key = COINBASE_API_KEY
        self.api_secret = COINBASE_API_SECRET
        self.api_passphrase = COINBASE_API_PASSPHRASE
        self.issuer = COINBASE_ISS
        self.org_id = COINBASE_ORG_ID
        self.pem_path = ensure_pem_file()
        # mode detection
        if advanced is None:
            self.advanced = bool(self.issuer or self.pem_path)
        else:
            self.advanced = advanced

        logger.info(f"[nija_hmac_client] Initialized. base={self.base} advanced={self.advanced} pem_exists={bool(self.pem_path)} issuer={bool(self.issuer)}")

    # Safe JSON parse helper
    def _safe_json(self, resp: requests.Response):
        try:
            return resp.json()
        except Exception:
            # non-json -> return raw text for debugging
            text = resp.text or ""
            logger.warning(f"[nija_hmac_client] ⚠️ JSON decode failed. Status: {resp.status_code}, Body: {text[:1000]!r}")
            return None

    # Retail HMAC (CB-ACCESS-SIGN) signing
    def _sign_retail(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + (body or "")
        # signature raw bytes then base64 encoded
        secret = (self.api_secret or "").encode()
        sig = base64.b64encode(hmac.new(secret, message.encode(), hashlib.sha256).digest()).decode()
        headers = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    # Advanced: generate JWT and set Authorization header
    def _auth_headers_advanced(self) -> dict:
        headers = {"Content-Type": "application/json"}
        # Attempt to generate JWT (short-lived)
        if self.pem_path and self.issuer:
            jwt_token = generate_jwt_with_pem(self.pem_path, self.issuer)
            if jwt_token:
                headers["Authorization"] = f"Bearer {jwt_token}"
                # include version header optionally
                headers["CB-VERSION"] = "2025-11-09"
                return headers
            else:
                logger.warning("[nija_hmac_client] Advanced mode configured but JWT generation failed.")
        else:
            logger.warning("[nija_hmac_client] Advanced mode but missing pem_path or issuer.")
        return headers

    # Generic request wrapper: returns (status_code, data_or_text)
    def request(self, method: str, path: str, data: dict | None = None, timeout: int = 15) -> Tuple[int | None, object | None]:
        """
        method: HTTP method (GET/POST)
        path: resource path, must start with '/'
        data: optional dict -> JSON body
        returns: (status_code, data) where data is dict/list if JSON parsed, else raw text if non-JSON
        """
        if not path.startswith("/"):
            path = "/" + path

        body = json.dumps(data) if data is not None else ""

        # If advanced, try advanced-style endpoints first (often /api/v3/...)
        if self.advanced:
            headers = self._auth_headers_advanced()
            # try the common Advanced endpoints that docs use:
            candidates = [
                (self.base, "/api/v3/brokerage" + path),
                (self.base, "/api/v3" + path),
                (RETAIL_BASE, "/api/v3/brokerage" + path),
                (RETAIL_BASE, "/api/v3" + path),
            ]
            for base, p in candidates:
                url = base.rstrip("/") + p
                logger.info(f"[nija_hmac_client] Trying Advanced URL {url}")
                try:
                    resp = requests.request(method, url, headers=headers, timeout=timeout, data=body if body else None)
                except Exception as e:
                    logger.exception(f"[nija_hmac_client] Request to {url} failed: {e}")
                    continue
                parsed = self._safe_json(resp)
                if resp.status_code == 200:
                    return resp.status_code, parsed if parsed is not None else (resp.text or "")
                # keep trying if 404/401 etc, but return helpful debug info on last attempt
                logger.warning(f"[nija_hmac_client] Advanced try {url} returned {resp.status_code}. Body start: {repr(resp.text)[:500]}")
            # after tries, fallthrough to retail/hmac
            logger.warning("[nija_hmac_client] Advanced attempts failed; falling back to Retail HMAC attempts.")
            # continue to retail attempts

        # Retail HMAC attempts: use base and path directly and v2 variants
        headers = self._sign_retail(method, path, body)
        retail_candidates = [
            (self.base, path),
            (self.base, "/v2" + path),
            (RETAIL_BASE, path),
            (RETAIL_BASE, "/v2" + path),
        ]
        for base, p in retail_candidates:
            url = base.rstrip("/") + p
            logger.info(f"[nija_hmac_client] Trying Retail URL {url}")
            try:
                resp = requests.request(method, url, headers=headers, timeout=timeout, data=body if body else None)
            except Exception as e:
                logger.exception(f"[nija_hmac_client] Request to {url} failed: {e}")
                continue
            parsed = self._safe_json(resp)
            if resp.status_code == 200:
                return resp.status_code, parsed if parsed is not None else (resp.text or "")
            logger.warning(f"[nija_hmac_client] Retail try {url} returned {resp.status_code}. Body start: {repr(resp.text)[:500]}")

        # Nothing returned 200
        return None, None

    # convenience: get accounts (tries v3/v2)
    def get_accounts(self) -> Tuple[int | None, object | None]:
        # prefer the most common path that the calling code expects
        # try /v3/accounts (raw), then /v3/brokerage/accounts, then /v2/accounts
        for p in ["/v3/accounts", "/v3/brokerage/accounts", "/v2/accounts", "/accounts"]:
            status, data = self.request("GET", p)
            if status == 200 and data:
                return status, data
        # give up
        return None, None

# quick test if run as script (non-crashing)
if __name__ == "__main__":
    logger.info("[nija_hmac_client] Running quick debug test of get_accounts()")
    client = CoinbaseClient()
    status, data = client.get_accounts()
    if status == 200:
        logger.info("[nija_hmac_client] Accounts fetch OK - sample:")
        try:
            items = data.get("data", data) if isinstance(data, dict) else data
            for i, acct in enumerate(items[:5]):
                logger.info(f" - {acct.get('name', acct)}")
        except Exception:
            logger.info(f"Data: {repr(data)[:500]}")
    else:
        logger.error(f"[nija_hmac_client] No accounts found. status={status} data={type(data)}. Check envs / keys / PEM.")
