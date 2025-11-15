# app/nija_client.py
# Requires: pyjwt, cryptography, requests, loguru

import os
import time
import json
import base64
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
    Minimal client that:
     - normalizes PEM from env (supports raw PEM or base64 encoded)
     - builds ES256 JWT using pyjwt / cryptography
     - provides .request(method, url, ...) wrapper that sets Authorization: Bearer <jwt>
    """

    def __init__(self, api_key: str, org_id: str = None, pem: str = None, kid: str = None, sandbox: bool = True):
        """
        api_key: e.g., "organizations/{org_id}/apiKeys/{key_id}" <- this is often what Coinbase expects as 'sub'
        org_id: optional, kept for completeness
        pem: full private key string (with -----BEGIN...----- lines) OR base64 of PEM
        kid: header.kid value published by Coinbase (use the exact value Coinbase shows)
        sandbox: if True, use sandbox base url for test requests
        """
        self.api_key = api_key
        self.org_id = org_id
        self.kid = kid or os.getenv("COINBASE_JWT_KID")
        self.sandbox = bool(os.getenv("SANDBOX", "1")) if pem is None else sandbox

        if not pem:
            pem = os.getenv("COINBASE_PEM_CONTENT") or os.getenv("COINBASE_PEM_B64")
        if not api_key:
            raise ValueError("api_key is required (COINBASE_API_KEY)")
        if not pem:
            raise ValueError("PEM not provided (COINBASE_PEM_CONTENT or COINBASE_PEM_B64)")

        self._private_key = self._load_pem_from_env(pem)
        logger.info("app.nija_client:__init__: CoinbaseClient initialized.")

    def _load_pem_from_env(self, pem_raw: str):
        """Accept either a literal PEM string or a base64-encoded PEM."""
        pem = pem_raw.strip()
        # detect base64 (no BEGIN line)
        if "-----BEGIN" not in pem:
            logger.info("PEM appears to be base64 encoded; decoding.")
            try:
                decoded = base64.b64decode(pem).decode("utf-8")
                pem = decoded
            except Exception as e:
                logger.error("Failed to decode base64 PEM: %s", e)
                raise

        # normalize escaped newlines (if someone pasted "\n")
        pem = pem.replace("\\n", "\n")
        # ensure the PEM header/footer exist
        if "-----BEGIN" not in pem or "-----END" not in pem:
            raise ValueError("PEM does not contain BEGIN/END markers after normalization.")

        private_key = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
            backend=default_backend()
        )
        return private_key

    def _build_jwt(self, expiry_seconds: int = 300):
        """Return a signed ES256 JWT string."""
        now = int(time.time())
        payload = {
            "sub": self.api_key,
            "iat": now,
            "exp": now + expiry_seconds
        }
        headers = {"alg": "ES256"}
        if self.kid:
            headers["kid"] = self.kid

        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        # token may be bytes in some pyjwt versions; ensure string
        if isinstance(token, bytes):
            token = token.decode("utf-8")

        # Display header/payload in logs (unverified) for debugging
        try:
            hdr = jwt.get_unverified_header(token)
            pl = jwt.decode(token, options={"verify_signature": False})
            logger.info("JWT header.kid: " + str(hdr.get("kid")))
            logger.info("JWT payload.sub: " + str(pl.get("sub")))
            logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())
        except Exception:
            logger.exception("Failed to decode JWT for logging (non-fatal)")

        return token

    def request(self, method: str, url: str, **kwargs):
        """Perform a request attaching Authorization: Bearer <jwt> header."""
        token = self._build_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        # if you need a CB-VERSION or other headers add them here if needed
        return requests.request(method, url, headers=headers, **kwargs)

    def sandbox_accounts(self):
        """Simple convenience to fetch sandbox /accounts (note: valid for sandbox endpoints)"""
        base = "https://api-public.sandbox.pro.coinbase.com"
        return self.request("GET", f"{base}/accounts")

    def cdpexample(self, path="/v1/somepath"):
        """If using the CDP/AdvancedTrade endpoints, set the CDP base."""
        base = "https://api.cdp.coinbase.com" if not self.sandbox else "https://api-public.sandbox.cdp.coinbase.com"
        return self.request("GET", base + path)
