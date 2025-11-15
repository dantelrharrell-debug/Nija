# app/nija_client.py
import os
import json
import time
import datetime
import logging
import requests
import base64
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self, api_key: str, org_id: str, pem: Optional[str] = None,
                 kid: Optional[str] = None, sandbox: bool = False,
                 rest_key: Optional[str] = None,
                 rest_secret: Optional[str] = None,
                 rest_passphrase: Optional[str] = None):
        self.api_key = api_key
        self.org_id = org_id
        self._private_key = None
        self.kid = kid
        self.sandbox = sandbox
        self.rest_key = rest_key or os.environ.get("COINBASE_REST_KEY")
        self.rest_secret = rest_secret or os.environ.get("COINBASE_REST_SECRET")
        self.rest_passphrase = rest_passphrase or os.environ.get("COINBASE_REST_PASSPHRASE")

        if pem:
            if "\\n" in pem:
                pem = pem.replace("\\n", "\n")
            self._private_key = serialization.load_pem_private_key(
                pem.encode("utf-8"), password=None, backend=default_backend()
            )

        logger.info("app.nija_client:__init__: CoinbaseClient initialized.")

    def _build_jwt(self) -> str:
        now = int(time.time())
        payload = {"sub": self.api_key, "iat": now, "exp": now + 300}
        headers = {"alg": "ES256", "kid": self.kid}

        if not self._private_key:
            raise RuntimeError("No PEM private key loaded for JWT.")

        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)

        # --- JWT debug/log snippet (inserted per your request) ---
        def verify_jwt_struct(token):
            h_b64, p_b64, _ = token.split(".")
            def b64fix(s):
                return s + "=" * ((4 - len(s) % 4) % 4)
            header = json.loads(base64.urlsafe_b64decode(b64fix(h_b64)))
            payload = json.loads(base64.urlsafe_b64decode(b64fix(p_b64)))
            return header, payload

        try:
            header, payload = verify_jwt_struct(token)
            logger.info(f"_build_jwt: JWT header.kid: {header.get('kid')}")
            logger.info(f"_build_jwt: JWT payload.sub: {payload.get('sub')}")
            logger.info(f"_build_jwt: Server UTC time: {datetime.datetime.utcnow().isoformat()}")
        except Exception as e:
            logger.exception("Failed to decode/log JWT contents: {}", e)
        # --- end JWT debug/log snippet ---

        return token

    def request_jwt(self, method: str, url: str, **kwargs):
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, url, headers=headers, **kwargs)

    def request_rest(self, method: str, url: str, **kwargs):
        body = ""
        if "json" in kwargs:
            body = json.dumps(kwargs.pop("json"))
            kwargs["data"] = body
        elif "data" in kwargs:
            body = kwargs.get("data", "")

        headers = kwargs.pop("headers", {})

        if not all([self.rest_key, self.rest_secret, self.rest_passphrase]):
            msg = (
                "REST API credentials missing. Set these vars:\n"
                "COINBASE_REST_KEY, COINBASE_REST_SECRET, COINBASE_REST_PASSPHRASE"
            )
            logger.error(msg)
            raise RuntimeError(msg)

        # Build HMAC signature here (not implemented in snippet)
        # h = self._build_rest_headers(method, url, body)
        # headers.update(h)

        return requests.request(method, url, headers=headers, data=body, **kwargs)

    def request_auto(self, method: str, url: str, **kwargs):
        parsed = requests.utils.urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        if "api.coinbase.com" in host or "pro.coinbase.com" in host:
            if all([self.rest_key, self.rest_secret, self.rest_passphrase]):
                return self.request_rest(method, url, **kwargs)
            if self._private_key:
                logger.warning("REST creds missing — falling back to JWT")
                return self.request_jwt(method, url, **kwargs)
            raise RuntimeError("No REST creds and no PEM available.")

        if "cdp" in host or "advanced-trade" in host:
            return self.request_jwt(method, url, **kwargs)

        if self._private_key:
            return self.request_jwt(method, url, **kwargs)

        return self.request_rest(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        return self.request_auto(method, url, **kwargs)

    def sandbox_accounts(self):
        base = "https://api-public.sandbox.pro.coinbase.com"
        return self.request_auto("GET", f"{base}/accounts")
