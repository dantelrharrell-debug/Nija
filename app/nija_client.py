# app/nija_client.py
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru
"""
CoinbaseClient
- Creates JWTs from an EC private key (PEM) and calls JWT-auth endpoints.
- Builds CB-ACCESS-* headers for REST API calls (HMAC-SHA256).
- request_auto() inspects the URL and chooses REST vs JWT as appropriate.
- Exposes sandbox_accounts() convenience call.
Environment variables used (can also pass to constructor):
- COINBASE_API_KEY or api_key (sub for JWT 'sub', typically organizations/{org_id}/apiKeys/{key_id})
- COINBASE_PEM_CONTENT or COINBASE_PEM_B64 or pem (PEM string or base64-encoded PEM)
- COINBASE_JWT_KID or jwt_kid (key id to place in JWT header)
- COINBASE_REST_KEY / COINBASE_REST_SECRET / COINBASE_REST_PASSPHRASE (for REST HMAC)
- SANDBOX boolean-ish variable not required here but used elsewhere if you choose
"""

import os
import time
import datetime
import jwt
import requests
import base64
import json
import hmac
import hashlib
from urllib.parse import urlparse
from typing import Optional, Tuple

from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Setup basic logger if user hasn't
logger.remove()
logger.add(lambda m: print(m, end=""), level="INFO")  # simple console logging


class CoinbaseClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        org_id: Optional[str] = None,
        pem: Optional[str] = None,
        jwt_kid: Optional[str] = None,
        rest_key: Optional[str] = None,
        rest_secret: Optional[str] = None,
        rest_passphrase: Optional[str] = None,
    ):
        """
        Provide credentials either via constructor or environment variables.

        api_key: The 'sub' claim for JWT (often "organizations/{org_id}/apiKeys/{key_id}")
        pem: full PEM string (-----BEGIN ...). If not raw PEM, the code will check for base64 env var.
        jwt_kid: key id to set in JWT header (kid)
        rest_key/rest_secret/rest_passphrase: for REST HMAC authentication
        """
        # Prefer constructor args, fallback to environment variables
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.jwt_kid = jwt_kid or os.getenv("COINBASE_JWT_KID") or os.getenv("COINBASE_KEY_ID")
        self.rest_key = rest_key or os.getenv("COINBASE_REST_KEY") or os.getenv("COINBASE_API_KEY")
        self.rest_secret = rest_secret or os.getenv("COINBASE_REST_SECRET") or os.getenv("COINBASE_API_SECRET")
        self.rest_passphrase = rest_passphrase or os.getenv("COINBASE_REST_PASSPHRASE") or os.getenv("COINBASE_API_PASSPHRASE")

        # PEM handling: accept direct PEM or base64 encoded
        pem_env_raw = pem or os.getenv("COINBASE_PEM_CONTENT")
        pem_b64_env = os.getenv("COINBASE_PEM_B64")
        self._private_key = None
        if pem_env_raw:
            try:
                # Accept if user included "\n" literal sequences
                pem_clean = pem_env_raw.replace("\\n", "\n")
                self._private_key = serialization.load_pem_private_key(
                    pem_clean.encode("utf-8"), password=None, backend=default_backend()
                )
            except Exception:
                # try base64 decode fallback
                try:
                    pem_decoded = base64.b64decode(pem_env_raw)
                    self._private_key = serialization.load_pem_private_key(
                        pem_decoded, password=None, backend=default_backend()
                    )
                except Exception as e:
                    logger.warning("Failed to load PEM from COINBASE_PEM_CONTENT: %s", e)
                    self._private_key = None
        elif pem_b64_env:
            try:
                pem_decoded = base64.b64decode(pem_b64_env)
                self._private_key = serialization.load_pem_private_key(
                    pem_decoded, password=None, backend=default_backend()
                )
            except Exception as e:
                logger.warning("Failed to load PEM from COINBASE_PEM_B64: %s", e)
                self._private_key = None

        logger.info("app.nija_client:__init__: CoinbaseClient initialized.")
        if self._private_key:
            # attempt one jwt build to log kid + sub (non-sensitive)
            try:
                header, payload = self._build_jwt_struct_preview()
                logger.info("_build_jwt: JWT header.kid: %s", header.get("kid"))
                logger.info("_build_jwt: JWT payload.sub: %s", payload.get("sub"))
                logger.info("_build_jwt: Server UTC time: %s", datetime.datetime.utcnow().isoformat())
            except Exception:
                # ignore preview failures
                pass

    # -----------------------
    # JWT helpers
    # -----------------------
    def _build_jwt(self, expire_seconds: int = 300) -> str:
        """
        Build and return a JWT (ES256) signed with the PEM private key.
        Requires: self._private_key and self.api_key/sub present.
        """
        if not self._private_key:
            raise RuntimeError("No PEM private key available for JWT generation.")

        sub = self.api_key or os.getenv("COINBASE_API_KEY")
        if not sub:
            raise RuntimeError("COINBASE_API_KEY (JWT subject) missing.")

        now = int(time.time())
        payload = {"sub": sub, "iat": now, "exp": now + expire_seconds}
        headers = {"alg": "ES256"}
        if self.jwt_kid:
            headers["kid"] = self.jwt_kid

        # pyjwt accepts private key object from cryptography
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        # pyjwt returns str in modern versions
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def _build_jwt_struct_preview(self) -> Tuple[dict, dict]:
        """
        Build a short JWT and return header, payload (decoded) for logging/debugging.
        Doesn't verify expiration.
        """
        token = self._build_jwt()
        return verify_jwt_struct(token)

    # -----------------------
    # REST HMAC helper (CB-ACCESS-*)
    # -----------------------
    def _build_rest_headers(self, method: str, url: str, body: str = "") -> dict:
        """
        Build Coinbase REST headers CB-ACCESS-KEY, CB-ACCESS-SIGN, CB-ACCESS-TIMESTAMP, CB-ACCESS-PASSPHRASE.
        rest_secret may be base64-encoded; Coinbase's secret is usually a raw base64 string.
        """
        if not all([self.rest_key, self.rest_secret, self.rest_passphrase]):
            raise RuntimeError("REST API credentials missing (rest_key/rest_secret/rest_passphrase).")

        # Coinbase expects timestamp + method + requestPath + body (body empty string if no body)
        ts = str(int(time.time()))
        parsed = urlparse(url)
        request_path = parsed.path
        if parsed.query:
            request_path += "?" + parsed.query

        prehash = ts + method.upper() + request_path + (body or "")
        # rest_secret is typically base64-encoded string from Coinbase UI
        secret_bytes = None
        try:
            # try base64 decode (Coinbase gives base64 string)
            secret_bytes = base64.b64decode(self.rest_secret)
        except Exception:
            # if not base64, use as-is bytes
            secret_bytes = self.rest_secret.encode("utf-8")

        signature = base64.b64encode(hmac.new(secret_bytes, prehash.encode("utf-8"), hashlib.sha256).digest()).decode()

        headers = {
            "CB-ACCESS-KEY": self.rest_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.rest_passphrase,
            "Content-Type": "application/json",
        }
        return headers

    # -----------------------
    # Request wrappers
    # -----------------------
    def request_jwt(self, method: str, url: str, **kwargs):
        """
        Perform HTTP request using JWT in Authorization: Bearer <token>.
        """
        token = self._build_jwt()
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, url, headers=headers, **kwargs)

    def request_rest(self, method: str, url: str, **kwargs):
        """
        Perform HTTP request using REST HMAC headers.
        Accepts json= or data= in kwargs. If json= provided, it is serialized to data.
        """
        body = ""
        if "json" in kwargs:
            body = json.dumps(kwargs.get("json"))
            kwargs.pop("json", None)
            kwargs["data"] = body
        elif "data" in kwargs:
            body = kwargs.get("data", "")

        headers = kwargs.pop("headers", {}) or {}

        if not all([self.rest_key, self.rest_secret, self.rest_passphrase]):
            msg = (
                "REST API credentials missing. Set these vars:\n"
                "COINBASE_REST_KEY, COINBASE_REST_SECRET, COINBASE_REST_PASSPHRASE"
            )
            logger.error(msg)
            raise RuntimeError(msg)

        h = self._build_rest_headers(method, url, body)
        headers.update(h)

        return requests.request(method, url, headers=headers, data=body, **kwargs)

    def request_auto(self, method: str, url: str, **kwargs):
        """
        Automatically choose JWT or REST depending on the hostname and credentials available.
        - If host is api.coinbase.com or pro.coinbase.com => prefer REST when REST creds available
          (Coinbase Pro/public endpoints often want CB-ACCESS-*). If REST creds missing but PEM exists,
          will fall back to JWT.
        - If host includes 'cdp' or 'advanced-trade' => use JWT
        - Otherwise: prefer JWT if PEM present, else REST.
        """
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Use path to detect pro endpoints
        if "api.coinbase.com" in host or "pro.coinbase.com" in host or "api-public.sandbox.pro.coinbase.com" in host:
            if all([self.rest_key, self.rest_secret, self.rest_passphrase]):
                return self.request_rest(method, url, **kwargs)
            if self._private_key:
                logger.warning("REST creds missing — falling back to JWT")
                return self.request_jwt(method, url, **kwargs)
            raise RuntimeError("No REST creds and no PEM available.")
        if "cdp" in host or "advanced-trade" in host:
            # CDP / advanced trade use JWT auth
            return self.request_jwt(method, url, **kwargs)

        # default: use JWT if available
        if self._private_key:
            return self.request_jwt(method, url, **kwargs)
        # fallback to REST
        return self.request_rest(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        """
        Public alias for request_auto
        """
        return self.request_auto(method, url, **kwargs)

    # -----------------------
    # Convenience / examples
    # -----------------------
    def sandbox_accounts(self):
        """
        Convenience helper for sandbox accounts endpoint (Coinbase Pro sandbox)
        """
        base = "https://api-public.sandbox.pro.coinbase.com"
        return self.request_auto("GET", f"{base}/accounts")


# -----------------------
# Utility: inspect JWT structure (safe, local decoding)
# -----------------------
def verify_jwt_struct(token: str) -> Tuple[dict, dict]:
    """
    Return (header, payload) decoded from the JWT without verifying signature.
    Useful for logging kid and sub claims.
    """
    import base64 as _b64mod
    import json as _json

    header_b64, payload_b64, _ = token.split(".")
    # pad base64 as needed
    def _b64pad(s: str):
        return s + "=" * (-len(s) % 4)

    header = _json.loads(_b64mod.urlsafe_b64decode(_b64pad(header_b64)))
    payload = _json.loads(_b64mod.urlsafe_b64decode(_b64pad(payload_b64)))
    return header, payload


# -----------------------
# Example usage (commented)
# -----------------------
# if __name__ == "__main__":
#     c = CoinbaseClient()
#     try:
#         r = c.sandbox_accounts()
#         print("status", r.status_code, r.text[:400])
#     except Exception as e:
#         print("error:", e)
