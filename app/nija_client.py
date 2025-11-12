# app/nija_client.py
import os
import time
import base64
import requests
import jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        # Read envs
        self.base_url = os.getenv("COINBASE_BASE", "https://api.coinbase.com/v2")
        self.auth_mode = os.getenv("COINBASE_AUTH_MODE", "advanced").lower()
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.key_id = os.getenv("COINBASE_KEY_ID")
        self.jwt_iss = os.getenv("COINBASE_JWT_ISS")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        # New: allow base64-encoded PEM in env (useful for single-line secret editors)
        self.pem_content_raw = os.getenv("COINBASE_JWT_PEM")
        self.pem_b64 = os.getenv("COINBASE_JWT_PEM_B64")
        self.pem_content = None

        # Normalize / load PEM
        self._load_pem()

        if self.auth_mode == "advanced":
            missing = [v for v in ["COINBASE_KEY_ID", "COINBASE_JWT_ISS", "COINBASE_JWT_PEM", "COINBASE_ORG_ID"]
                       if not os.getenv(v)]
            if missing:
                logger.warning("Advanced auth enabled but missing env vars: %s. Key ID must be a simple string (e.g. 'd3c4f66b-...').", missing)
        else:
            logger.info("Using standard API key auth (COINBASE_AUTH_MODE=%s).", self.auth_mode)

        logger.info("CoinbaseClient initialized. base=%s auth_mode=%s", self.base_url, self.auth_mode)

    def _clean_candidate(self, s: str) -> str | None:
        if not s:
            return None
        s = s.strip()
        # remove surrounding quotes if pasted with quotes
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        # convert literal \n sequences into real newlines if necessary
        if "\\n" in s and "\n" not in s:
            s = s.replace("\\n", "\n")
        return s

    def _load_pem(self):
        # 1) direct PEM env
        if self.pem_content_raw:
            cleaned = self._clean_candidate(self.pem_content_raw)
            if cleaned and cleaned.startswith("-----BEGIN") and "PRIVATE KEY-----" in cleaned:
                self.pem_content = cleaned
                logger.debug("Loaded PEM from COINBASE_JWT_PEM (direct).")
            else:
                # keep cleaned for fallback, but warn
                self.pem_content = cleaned
                logger.debug("COINBASE_JWT_PEM provided but did not look like a normal PEM (will attempt decoding/normalization).")

        # 2) fallback: base64 encoded PEM env
        if not self.pem_content and self.pem_b64:
            cleaned_b64 = self._clean_candidate(self.pem_b64)
            try:
                decoded = base64.b64decode(cleaned_b64)
                decoded_str = decoded.decode("utf-8", errors="ignore")
                if decoded_str.startswith("-----BEGIN") and "PRIVATE KEY-----" in decoded_str:
                    self.pem_content = decoded_str
                    logger.debug("Loaded PEM from COINBASE_JWT_PEM_B64 (decoded).")
                else:
                    logger.warning("COINBASE_JWT_PEM_B64 decoded but does not contain PEM framing.")
            except Exception as e:
                logger.exception("Failed to decode COINBASE_JWT_PEM_B64: %s", e)

        # 3) normalize escaped newlines if needed
        if self.pem_content and "\\n" in self.pem_content and "\n" not in self.pem_content:
            self.pem_content = self.pem_content.replace("\\n", "\n")
            logger.debug("Normalized PEM by replacing literal \\n with real newlines.")

        # 4) final sanity check
        if self.pem_content:
            if not (self.pem_content.startswith("-----BEGIN") and "END" in self.pem_content):
                logger.warning("PEM present but does not look well-formed (missing BEGIN/END).")
        else:
            logger.debug("No PEM content available from COINBASE_JWT_PEM or COINBASE_JWT_PEM_B64.")

    def _get_jwt(self):
        """Build a short-lived ES256 JWT for Coinbase Advanced auth"""
        # quick validation
        if not all([self.key_id, self.jwt_iss, self.pem_content, self.org_id]):
            logger.error("Cannot build JWT: missing key_id/pem/jwt_iss/org_id")
            return None

        try:
            iat = int(time.time())
            payload = {
                "iss": self.jwt_iss,
                "iat": iat,
                "exp": iat + 60,  # 60 seconds
                "sub": self.org_id,
            }
            headers = {"kid": str(self.key_id)}
            token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers=headers)
            return token
        except Exception as e:
            logger.exception("Failed to generate JWT: %s", e)
            return None

    def _headers(self):
        if self.auth_mode == "advanced":
            token = self._get_jwt()
            if token:
                return {"Authorization": f"Bearer {token}"}
            else:
                logger.error("Advanced auth enabled but JWT generation failed.")
                return {}
        elif self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        else:
            logger.error("No authentication method available (no API key and advanced auth failed).")
            return {}

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())

        try:
            r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning("HTTP request failed for %s: %s", url, e)
            return None
        except Exception as e:
            logger.exception("Request error for %s: %s", url, e)
            return None

    def get_accounts(self):
        data = self._request("GET", "/accounts")
        if data:
            return data.get("data", [])
        return None
