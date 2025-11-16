# app/nija_client.py
"""
Robust Coinbase Advanced (CDP) JWT client for /api/v3/brokerage endpoints.
Drop this file at app/nija_client.py and import CoinbaseClient from it.
"""

import os
import time
import json
import logging
import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# configure logging (loguru not required here; use std logging to avoid extra deps)
logger = logging.getLogger("nija_coinbase")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment names used in your project
ENV_API_KEY = "COINBASE_API_KEY"    # the API Key ID (kid) from Coinbase Advanced
ENV_PEM     = "COINBASE_PEM"        # PEM private key content (may contain literal "\n")
ENV_ORG     = "COINBASE_ORG_ID"     # org id for brokerage
ENV_DEBUG   = "DEBUG_JWT"          # optional debug switch "1" to print JWT preview
ENV_LIVE    = "LIVE_TRADING"       # if "1" will attempt to place real orders (be careful)

# Default CB version header (not strictly required but safe)
CB_VERSION = "2025-11-12"

def _load_env_vars():
    api_key = os.environ.get(ENV_API_KEY)
    raw_pem = os.environ.get(ENV_PEM, "")
    org_id = os.environ.get(ENV_ORG)

    # Common PEM issues: CI systems store newlines as literal "\n" — fix that
    pem = raw_pem
    if pem and "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    # Strip surrounding quotes if the .env included them
    if pem.startswith('"') and pem.endswith('"'):
        pem = pem[1:-1]
    if pem.startswith("'") and pem.endswith("'"):
        pem = pem[1:-1]

    return api_key, pem, org_id

def _load_private_key(pem_text):
    if not pem_text:
        raise ValueError("Empty PEM provided")
    try:
        return serialization.load_pem_private_key(
            pem_text.encode("utf-8"),
            password=None,
            backend=default_backend()
        )
    except Exception as e:
        # Re-raise with clearer message for logs
        raise ValueError(f"Unable to load PEM private key: {e}")

class CoinbaseClient:
    def __init__(self, api_key_id=None, org_id=None, private_key_obj=None):
        # lazy-load from environment if not supplied
        self.api_key_id = api_key_id
        self.org_id = org_id
        self.private_key = private_key_obj
        self.base_host = "https://api.coinbase.com"
        self.base_prefix = "/api/v3/brokerage"

        if not self.api_key_id or not self.org_id or not self.private_key:
            # try to load from environment
            env_api, env_pem, env_org = _load_env_vars()
            if not self.api_key_id:
                self.api_key_id = env_api
            if not self.org_id:
                self.org_id = env_org
            if not self.private_key and env_pem:
                try:
                    self.private_key = _load_private_key(env_pem)
                except Exception as e:
                    # Keep object constructed but private_key None and log failure — avoids crash
                    logger.error("Failed to load private key during init: %s", e)
                    self.private_key = None

        logger.info("CoinbaseClient init: api_key_id=%s  org_id=%s  has_private_key=%s",
                    "<set>" if self.api_key_id else "<missing>",
                    self.org_id or "<missing>",
                    bool(self.private_key))

    def _generate_jwt(self, method: str, request_path: str) -> str:
        """
        Create ES256 JWT per Coinbase CDP docs.
        request_path must be the exact path that will be requested (e.g. '/api/v3/brokerage/organizations/<org>/accounts')
        """
        if not self.private_key:
            raise RuntimeError("Private key not loaded; cannot generate JWT")

        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 120,  # short-lived
            "sub": self.api_key_id,
            "request_path": request_path,
            "method": method.upper()
        }
        headers = {"alg": "ES256", "kid": self.api_key_id}

        # Use PyJWT to sign; private_key is a cryptography key object
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)

        if os.environ.get(ENV_DEBUG) == "1":
            try:
                # Safe preview only
                logger.info("DEBUG_JWT: token_preview=%s", token[:200])
                # Show decoded header/payload without signature verification
                hdr = jwt.get_unverified_header(token)
                pl  = jwt.decode(token, options={"verify_signature": False})
                logger.info("DEBUG_JWT: header=%s", json.dumps(hdr))
                logger.info("DEBUG_JWT: payload=%s", json.dumps(pl))
            except Exception:
                logger.exception("DEBUG_JWT: failed to decode token for debug")

        return token

    def _request(self, method: str, path: str, **kwargs):
        """
        Internal helper to sign the request and call requests.
        path must start with /api/v3/...
        """
        url = self.base_host + path
        if not self.private_key or not self.api_key_id:
            raise RuntimeError("Missing credentials (private_key or api_key_id)")

        token = self._generate_jwt(method, path)
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {token}",
            "CB-VERSION": CB_VERSION,
            "User-Agent": "nija-bot/1.0"
        })

        logger.debug("Request %s %s headers_preview=%s", method, url, {k: (v if k != "Authorization" else "<redacted>") for k, v in headers.items()})
        resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        if resp.status_code >= 400:
            # include response body in logs but limit length
            body = resp.text or "<no-body>"
            logger.error("HTTP %s %s -> %s ; body=%s", method, url, resp.status_code, body[:1000])
            # raise an HTTPError so callers can catch
            resp.raise_for_status()
        return resp

    # Public convenience methods
    def get_accounts(self):
        path = f"{self.base_prefix}/organizations/{self.org_id}/accounts"
        try:
            resp = self._request("GET", path)
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error fetching accounts: %s | Response: %s", e, getattr(e.response, "text", "No response"))
            return None
        except Exception as e:
            logger.exception("Unexpected error in get_accounts: %s", e)
            return None

    def get_historic_prices(self, symbol: str, granularity: str = "60"):
        path = f"{self.base_prefix}/market_data/{symbol}/candles?granularity={granularity}"
        try:
            resp = self._request("GET", path)
            return resp.json().get("data", [])
        except Exception as e:
            logger.exception("Historic prices failed: %s", e)
            return []

    def place_market_order(self, account_id: str, symbol: str, size: str):
        """
        Place a simple market order. Use with caution.
        NOTE: The exact order payload shape may differ; this is a general example.
        """
        path = f"{self.base_prefix}/orders"
        payload = {
            "account_id": account_id,
            "symbol": symbol,
            "side": "buy",
            "type": "market",
            "size": str(size)
        }
        try:
            resp = self._request("POST", path, json=payload)
            return resp.json()
        except Exception:
            logger.exception("Failed to place order")
            return None

# Small CLI/test runner so you can paste this file and run it directly for diagnostics.
def debug_run():
    api_key, pem, org = _load_env_vars()
    logger.info("ENV check: API_KEY set=%s, PEM set=%s, ORG set=%s", bool(api_key), bool(pem), bool(org))

    try:
        priv = _load_private_key(pem) if pem else None
    except Exception as e:
        priv = None
        logger.error("Failed to load private key: %s", e)

    client = CoinbaseClient(api_key_id=api_key, org_id=org, private_key_obj=priv)

    # Quick diagnostic: generate JWT and try accounts endpoint
    try:
        path = f"/api/v3/brokerage/organizations/{client.org_id}/accounts"
        jwt_token = None
        if client.private_key and client.api_key_id:
            jwt_token = client._generate_jwt("GET", path)
            logger.info("JWT preview (first200): %s", (jwt_token[:200] if jwt_token else "<none>"))
        else:
            logger.warning("Skipping JWT generation: missing key or api id")

        logger.info("Request URL: %s", client.base_host + path)
        try:
            resp = client._request("GET", path)
            logger.info("Accounts fetched OK: status=%s body=%s", resp.status_code, resp.text[:1000])
        except requests.exceptions.HTTPError as e:
            logger.error("Accounts HTTP error: %s | body=%s", e, getattr(e.response, "text", "No response"))
        except Exception as e:
            logger.exception("Accounts request failed: %s", e)

    except Exception:
        logger.exception("Debug run failed")

if __name__ == "__main__":
    # when invoked directly, run the diagnostics once and exit (no infinite loop)
    debug_run()
