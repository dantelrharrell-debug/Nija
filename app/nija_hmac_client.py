# nija_hmac_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import logging
from typing import Tuple, Any

logger = logging.getLogger("nija_hmac_client")
logger.setLevel(logging.INFO)

# Environment config
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")               # Retail HMAC key id or CDP key ("organizations/.../apiKeys/...")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")       # Retail secret (base64) or CDP secret (string)
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # retail passphrase (optional)
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
COINBASE_ADVANCED_BASE = os.getenv("COINBASE_ADVANCED_BASE", "https://api.coinbase.com")  # usually https://api.coinbase.com
# NOTE: advanced endpoints use path prefix /api/v3/brokerage/...
# For CDP/JWT approach we also accept COINBASE_ISS / COINBASE_ORG_ID and COINBASE_PRIVATE_KEY_PATH if you generate JWTs locally.

# Attempt to import Coinbase Advanced helper (optional)
_have_advanced_helper = False
try:
    # coinbase-advanced-py provides helpers to format/generate JWTs
    from coinbase.jwt_generator import format_jwt_uri, build_rest_jwt  # type: ignore
    _have_advanced_helper = True
    logger.info("coinbase-advanced-py installed: will try JWT (Advanced) path when possible.")
except Exception:
    _have_advanced_helper = False
    logger.info("coinbase-advanced-py NOT available; will fall back to HMAC retail signing when needed.")


class CoinbaseClient:
    """
    Resilient client supporting:
      - Coinbase Advanced (v3 /api/v3/brokerage/*) using JWT (if helper installed)
      - Retail HMAC (CB-ACCESS-SIGN style; /v2/accounts, etc.) fallback
    Methods:
      - request(method, path, data=None) -> (status_code, parsed_or_raw)
    """

    def __init__(self):
        self.advanced = bool(os.getenv("COINBASE_PRIVATE_KEY_PATH") or os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID"))
        # For retail HMAC: COINBASE_API_SECRET is base64 string (we decode before using)
        try:
            if COINBASE_API_SECRET:
                # not all secret formats are base64; guard decode
                try:
                    base64.b64decode(COINBASE_API_SECRET)
                    self._secret_bytes = base64.b64decode(COINBASE_API_SECRET)
                except Exception:
                    # if it's not base64, use raw bytes
                    self._secret_bytes = COINBASE_API_SECRET.encode()
            else:
                self._secret_bytes = None
        except Exception:
            self._secret_bytes = None

        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced}")

    def _safe_json(self, resp: requests.Response) -> Any:
        """Try to parse JSON; on failure return raw text so callers won't crash."""
        try:
            return resp.json()
        except Exception:
            logger.warning(f"⚠️ JSON decode failed. Status: {resp.status_code}, Body: {resp.text[:200]}")
            return {"_raw_text": resp.text}

    def _retail_hmac_headers(self, method: str, path: str, body: str = "") -> dict:
        """
        Build CB-ACCESS headers for Retail API HMAC (v2 style).
        Uses base64-decoded secret for the HMAC.
        Prehash string per retail docs: timestamp + method + request_path + body
        Signature must be base64-encoded HMAC-SHA256 of prehash using secret_bytes.
        """
        ts = str(int(time.time()))
        request_path = path  # ensure leading slash for path like /v2/accounts
        prehash = ts + method.upper() + request_path + (body or "")
        secret = self._secret_bytes or b""
        sig = base64.b64encode(hmac.new(secret, prehash.encode(), hashlib.sha256).digest()).decode()
        headers = {
            "CB-ACCESS-KEY": COINBASE_API_KEY or "",
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        if COINBASE_API_PASSPHRASE:
            headers["CB-ACCESS-PASSPHRASE"] = COINBASE_API_PASSPHRASE
        return headers

    def _advanced_jwt_headers(self, method: str, path: str) -> dict:
        """If coinbase-advanced-py is installed, generate a JWT for the given method/path."""
        if not _have_advanced_helper:
            raise RuntimeError("Advanced JWT helper not available")
        # build a formatted uri for jwt generator (see coinbase.jwt_generator docs)
        # Format should be e.g. "GET api.coinbase.com/api/v3/brokerage/accounts"
        host = COINBASE_ADVANCED_BASE.replace("https://", "").replace("http://", "").rstrip("/")
        formatted = f"{method.upper()} {host}{path}"
        # build_rest_jwt takes (uri, key, secret) or similar depending on helper. We'll attempt to call it.
        try:
            # build_rest_jwt returns a dict or token string depending on version; handle both
            token = build_rest_jwt(formatted, COINBASE_API_KEY, COINBASE_API_SECRET)
            if isinstance(token, dict) and "token" in token:
                token = token["token"]
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        except Exception as e:
            logger.exception("Advanced JWT build failed: %s", e)
            raise

    def request(self, method: str = "GET", path: str = "/v2/accounts", data: dict = None) -> Tuple[int, Any]:
        """
        Generic request:
          - If advanced is enabled, try advanced v3 endpoints (exact paths listed below)
          - If advanced fails or not configured, try retail HMAC endpoints
        Returns (status_code, parsed_json_or_raw_text)
        """
        body = ""
        if data is not None:
            body = requests.utils.requote_uri(json := requests.utils.requote_uri("")).strip()  # noop to avoid flake; we'll do normal json dump
        import json as _json
        body = _json.dumps(data) if data else ""

        # Candidate endpoints (try advanced first when advanced=True)
        advanced_paths = [
            "/api/v3/brokerage/accounts",  # canonical Advanced Trade accounts endpoint
            "/api/v3/accounts",            # possible variants
            "/api/v3/brokerage/accounts?include=portfolio",  # example variant
        ]
        retail_paths = [
            "/v2/accounts",  # classic retail endpoint
            "/accounts",
        ]

        # If web base differs, respect COINBASE_API_BASE
        base = COINBASE_API_BASE.rstrip("/")

        # 1) Try advanced JWT approach (strict v3 brokerage path)
        if self.advanced and _have_advanced_helper:
            for p in advanced_paths:
                full = base + p
                try:
                    headers = self._advanced_jwt_headers(method, p)
                except Exception:
                    headers = None
                try:
                    if not headers:
                        continue
                    resp = requests.request(method, full, headers=headers, data=body or None, timeout=15)
                    parsed = self._safe_json(resp)
                    if resp.status_code < 400:
                        return resp.status_code, parsed
                    # if 404/401 etc -> log and try next path/fallback
                    logger.warning("Advanced attempt %s returned %s", full, resp.status_code)
                except Exception as e:
                    logger.exception("Advanced request to %s failed: %s", full, e)

        # 2) Fallback: retail HMAC style against retail endpoints (use base retail URL if set)
        # Decide retail base: if user set COINBASE_API_BASE explicitly to retail API host, use it;
        # otherwise try common retail base
        retail_base_candidates = [COINBASE_API_BASE.rstrip("/"), "https://api.coinbase.com", "https://api.cdp.coinbase.com"]
        tried = set()
        for base_candidate in retail_base_candidates:
            for p in retail_paths:
                base_candidate = base_candidate.rstrip("/")
                if (base_candidate, p) in tried:
                    continue
                tried.add((base_candidate, p))
                full = base_candidate + p
                try:
                    headers = self._retail_hmac_headers(method, p, body)
                    resp = requests.request(method, full, headers=headers, data=body or None, timeout=15)
                    parsed = self._safe_json(resp)
                    # On success or non-json we return status and parsed/raw object.
                    return resp.status_code, parsed
                except Exception as e:
                    logger.exception("Retail HMAC request to %s failed: %s", full, e)
                    # keep trying next candidate

        # If we reach here nothing worked
        return 520, {"error": "no endpoint succeeded"}
