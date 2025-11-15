# app/nija_client.py
# Requires: pyjwt, cryptography, requests, loguru

import os
import time
import json
import base64
import hmac
import hashlib
import datetime
from loguru import logger
import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda m: print(m, end=""), level="INFO")


class CoinbaseClient:
    """
    Dual-mode Coinbase client:
      - JWT bearer (ES256) for CDP/AdvancedTrade endpoints (signed with PEM)
      - HMAC REST v2 / Pro style (CB-ACCESS-KEY, SIGN, TIMESTAMP) for api.coinbase.com / pro endpoints
    It will attach JWT when calling request_jwt(), or HMAC when calling request_rest().
    A convenience method .request_auto() will select HMAC for api.coinbase.com/* or JWT for CDP if desired.
    """

    def __init__(self, api_key: str = None, org_id: str = None, pem: str = None,
                 kid: str = None, rest_key: str = None, rest_secret: str = None, rest_passphrase: str = None,
                 sandbox: bool = True):
        # JWT-related
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self.kid = kid or os.getenv("COINBASE_JWT_KID")
        pem_raw = pem or os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_PEM_B64")
        self._private_key = None
        if pem_raw:
            self._private_key = self._load_pem_from_env(pem_raw)

        # REST HMAC-related
        self.rest_key = rest_key or os.getenv("COINBASE_API_KEY") or os.getenv("COINBASE_REST_KEY")
        self.rest_secret = rest_secret or os.getenv("COINBASE_API_SECRET") or os.getenv("COINBASE_REST_SECRET")
        self.rest_passphrase = rest_passphrase or os.getenv("COINBASE_API_PASSPHRASE") or os.getenv("COINBASE_REST_PASSPHRASE")

        self.sandbox = bool(int(os.getenv("SANDBOX", "1"))) if sandbox is None else sandbox

        logger.info("app.nija_client:__init__: CoinbaseClient initialized.")

    # --------------------
    # PEM loader + JWT build
    # --------------------
    def _load_pem_from_env(self, pem_raw: str):
        pem = pem_raw.strip()
        if "-----BEGIN" not in pem:
            # probably base64
            try:
                pem = base64.b64decode(pem).decode("utf-8")
                logger.info("Decoded base64 PEM")
            except Exception as e:
                logger.exception("PEM base64 decode failed")
                raise
        pem = pem.replace("\\n", "\n")
        if "-----BEGIN" not in pem or "-----END" not in pem:
            raise ValueError("PEM missing BEGIN/END after normalization")
        private_key = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
            backend=default_backend()
        )
        return private_key

    def _build_jwt(self, expiry_seconds: int = 300):
        if not self._private_key:
            raise RuntimeError("No private key available for JWT signing.")
        now = int(time.time())
        payload = {"sub": self.api_key, "iat": now, "exp": now + expiry_seconds}
        headers = {"alg": "ES256"}
        if self.kid:
            headers["kid"] = self.kid
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        # log header & payload for quick debugging
        try:
            hdr = jwt.get_unverified_header(token)
            pl = jwt.decode(token, options={"verify_signature": False})
            logger.info(f"JWT header.kid: {hdr.get('kid')}")
            logger.info(f"JWT payload.sub: {pl.get('sub')}")
            logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())
        except Exception:
            logger.exception("JWT debug decode failed (non-fatal)")
        return token

    # --------------------
    # REST HMAC signing for api.coinbase.com / Pro endpoints
    # --------------------
    def _build_rest_headers(self, method: str, url: str, body: str = ""):
        """
        Build CB-ACCESS-* headers for REST v2 / Pro style endpoints.
        Expects self.rest_key and self.rest_secret (base64 or raw).
        """
        if not all([self.rest_key, self.rest_secret, self.rest_passphrase]):
            raise RuntimeError("REST API credentials missing (rest_key/rest_secret/rest_passphrase).")

        # coinbase expects timestamp + method + request_path + body
        parsed = requests.utils.urlparse(url)
        request_path = parsed.path or "/"
        if parsed.query:
            request_path += "?" + parsed.query

        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + request_path + (body or "")
        # rest_secret may be base64 or plain raw secret - Coinbase Pro uses plain secret (not base64)
        secret = self.rest_secret
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        else:
            secret_bytes = secret

        signature = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "CB-ACCESS-KEY": self.rest_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.rest_passphrase,
            "Content-Type": "application/json"
        }
        return headers

    # --------------------
    # Request helpers
    # --------------------
    def request_jwt(self, method: str, url: str, **kwargs):
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, url, headers=headers, **kwargs)

    def request_rest(self, method: str, url: str, **kwargs):
        body = ""
        if "json" in kwargs:
            body = json.dumps(kwargs.get("json"))
            kwargs.pop("json", None)
            kwargs["data"] = body
        elif "data" in kwargs:
            body = kwargs.get("data", "")

        headers = kwargs.pop("headers", {})
        try:
            h = self._build_rest_headers(method, url, body)
        except Exception as e:
            logger.exception("Failed to create REST headers")
            raise
        headers.update(h)
        return requests.request(method, url, headers=headers, data=body, **kwargs)

    def request_auto(self, method: str, url: str, **kwargs):
        """
        Auto-selects auth method:
          - If host contains 'coinbase.com' and path is /v2 or pro, use REST HMAC
          - If host contains 'cdp' or sandbox CDP endpoint, use JWT
        You can override by calling request_jwt() or request_rest() directly.
        """
        parsed = requests.utils.urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        # heuristic: api.coinbase.com / api.pro.coinbase.com -> REST HMAC
        if "api.coinbase.com" in host or "pro.coinbase.com" in host or path.startswith("/v2") or path.startswith("/accounts"):
            return self.request_rest(method, url, **kwargs)

        # heuristic: cdp/advanced trade endpoints -> JWT
        if "cdp.coinbase.com" in host or "cdp" in host or "advanced-trade" in host or "sandbox" in host and "cdp" in host:
            return self.request_jwt(method, url, **kwargs)

        # default to JWT if available else REST
        if self._private_key:
            return self.request_jwt(method, url, **kwargs)
        return self.request_rest(method, url, **kwargs)

    # convenience
    def sandbox_accounts(self):
        base = "https://api-public.sandbox.pro.coinbase.com"
        return self.request_rest("GET", f"{base}/accounts")
