# nija_client.py
"""
Unified Coinbase client for Nija:
- Defines CoinbaseClient (and alias NijaCoinbaseClient) expected by start_bot.py
- Auto-selects Advanced (CDP) vs Pro endpoints via COINBASE_AUTH_MODE or advanced_mode flag
- Supports JWT (COINBASE_JWT or COINBASE_PEM_CONTENT + PyJWT) and HMAC signing (with robust secret handling)
- Exposes: fetch_accounts(), get_accounts(), get_balances(), list_accounts()
Drop this file into /app and redeploy.
"""

import os
import time
import json
import hmac
import hashlib
import base64
import requests
from loguru import logger

# Optional PyJWT support (used only if COINBASE_PEM_CONTENT provided)
try:
    import jwt as _pyjwt  # PyJWT
    PYJWT_AVAILABLE = True
except Exception:
    _pyjwt = None
    PYJWT_AVAILABLE = False

logger.configure(level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    def __init__(self,
                 api_key: str = None,
                 api_secret: str = None,
                 passphrase: str = None,
                 org_id: str = None,
                 base: str = None,
                 advanced_mode: bool = None):
        """
        Params:
          - advanced_mode: if True -> CDP (Coinbase Advanced); if False -> Pro (Exchange).
            If None -> decided from env COINBASE_AUTH_MODE: 'advanced'|'cdp'|'pro'|'exchange'
        Env used:
          COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE,
          COINBASE_ORG_ID, COINBASE_BASE, COINBASE_AUTH_MODE, COINBASE_JWT, COINBASE_PEM_CONTENT
        """
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self.custom_base = base or os.getenv("COINBASE_BASE", "").strip() or None

        # Decide advanced_mode: explicit param -> env -> default True (assume CDP if org_id present)
        if advanced_mode is not None:
            self.advanced_mode = bool(advanced_mode)
        else:
            auth_mode = os.getenv("COINBASE_AUTH_MODE", "").lower()
            if auth_mode in ("advanced", "cdp", "jwt"):
                self.advanced_mode = True
            elif auth_mode in ("pro", "exchange", "hmac"):
                self.advanced_mode = False
            else:
                # default: if org_id present or COINBASE_PEM_CONTENT -> assume advanced
                self.advanced_mode = bool(self.org_id or os.getenv("COINBASE_PEM_CONTENT"))

        # Choose base URLs
        if self.custom_base:
            self.base = self.custom_base.rstrip("/")
        else:
            self.base = "https://api.cdp.coinbase.com" if self.advanced_mode else "https://api.exchange.coinbase.com"

        # JWT priority: COINBASE_JWT env (already generated) or generate from PEM content if present
        self.jwt = os.getenv("COINBASE_JWT") or None
        pem_env = os.getenv("COINBASE_PEM_CONTENT") or None
        if not self.jwt and pem_env and PYJWT_AVAILABLE:
            try:
                self.jwt = self._jwt_from_pem_env(pem_env)
                logger.info("Ephemeral JWT generated from COINBASE_PEM_CONTENT")
            except Exception as e:
                logger.warning("Failed to create JWT from COINBASE_PEM_CONTENT: %s", e)
        # If jwt still None, we'll fall back to HMAC

        logger.info("nija_client startup: base=%s advanced_mode=%s jwt_set=%s api_key_set=%s",
                    self.base, self.advanced_mode, bool(self.jwt), bool(self.api_key))

    # ---------------- JWT helper ----------------
    def _jwt_from_pem_env(self, pem_content: str, ttl: int = 300) -> str:
        """
        Create ephemeral ES256 JWT from raw PEM text (COINBASE_PEM_CONTENT).
        Requires PyJWT installed in environment.
        """
        if not PYJWT_AVAILABLE:
            raise RuntimeError("PyJWT not available")
        now = int(time.time())
        payload = {"iat": now, "exp": now + int(ttl)}
        iss = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID")
        if iss:
            payload["iss"] = iss
        # Use PEM bytes directly
        token = _pyjwt.encode(payload, pem_content.encode("utf-8"), algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    # ---------------- signing helpers ----------------
    def _try_decode_secret(self, secret: str) -> bytes:
        """
        Coinbase secrets can be base64-encoded or raw strings. Try base64 then fall back to raw bytes.
        """
        if not secret:
            return b""
        try:
            # remove whitespace/newlines then decode
            s = secret.strip()
            return base64.b64decode(s)
        except Exception:
            return secret.encode("utf-8")

    def _hmac_signature(self, timestamp: str, method: str, path: str, body: str) -> str:
        """
        Create CB-ACCESS-SIGN style signature (base64 of HMAC-SHA256)
        - will attempt to decode secret from base64; if fails uses raw bytes
        """
        msg = timestamp + method.upper() + path + (body or "")
        key_bytes = self._try_decode_secret(self.api_secret or "")
        sig = hmac.new(key_bytes, msg.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("utf-8")

    # ---------------- header builder ----------------
    def _build_headers(self, method: str, path: str, body: str = "") -> dict:
        """
        Build headers for a request:
         - If JWT present -> Authorization Bearer
         - Otherwise HMAC style headers expected by Coinbase (CB-ACCESS-*)
        For CDP (Advanced) include CB-ACCESS-ORG when org id present.
        """
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        ts = str(int(time.time()))
        sign = self._hmac_signature(ts, method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sign,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        if self.passphrase is not None:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        if self.advanced_mode and (self.org_id or os.getenv("COINBASE_ORG_ID")):
            headers["CB-ACCESS-ORG"] = self.org_id or os.getenv("COINBASE_ORG_ID")
        return headers

    # ---------------- fetch accounts ----------------
    def fetch_accounts(self):
        """
        Fetch accounts (balances). Chooses endpoint depending on advanced_mode:
          - advanced_mode True -> GET {base}/accounts  (CDP / Advanced)
          - advanced_mode False -> GET {base}/accounts  (Pro / Exchange)
        Normalizes response into a list of account dicts.
        """
        # path used for signing must be the path portion e.g. "/accounts" or "/v2/accounts" depending on API
        # Use "/accounts" for both flows here — CDP expects /accounts; Pro expects /accounts as well.
        path = "/accounts"
        url = self.base.rstrip("/") + path
        try:
            headers = self._build_headers("GET", path, "")
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # Normalize shapes:
            if isinstance(data, dict):
                # CDP style may return {"accounts": [...]} or {"data": [...]}
                if "accounts" in data and isinstance(data["accounts"], list):
                    return data["accounts"]
                if "data" in data and isinstance(data["data"], list):
                    return data["data"]
                # In some CDP variants top-level object is account itself or another shape; try common keys
                # If contains currency & balance keys assume it's a single account; wrap it
                if "currency" in data and ("balance" in data or "available" in data):
                    return [data]
                # otherwise no known shape -> return empty list
                return []
            elif isinstance(data, list):
                return data
            else:
                return []
        except requests.exceptions.HTTPError as e:
            # Provide helpful log: status & body truncated
            try:
                body = resp.text[:1000]
            except Exception:
                body = "<unreadable>"
            logger.error("Error fetching accounts: %s - body: %s", e, body)
            return []
        except Exception as e:
            logger.error("Error fetching accounts: %s", e)
            return []

    # ---------------- convenience methods ----------------
    def get_accounts(self):
        return self.fetch_accounts()

    def list_accounts(self):
        return self.fetch_accounts()

    def get_account_balances(self):
        """
        Return dict mapping currency -> numeric balance (tries available/amount fields)
        """
        accs = self.fetch_accounts()
        out = {}
        for a in accs:
            # different shapes: { "currency": "USD", "balance": {"amount": "123"} }
            cur = a.get("currency") or a.get("asset") or a.get("money_currency")
            amt = None
            # common shapes:
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                out[cur] = float(amt or 0)
            except Exception:
                try:
                    out[cur] = float(str(amt).replace(",", "")) if amt is not None else 0.0
                except Exception:
                    out[cur] = 0.0
        return out

    def get_balances(self):
        return self.get_account_balances()

# Backwards-compatible alias many scripts expect
NijaCoinbaseClient = CoinbaseClient

# Ensure module-level names expected by start_bot.py exist
# (start_bot tries `from nija_client import CoinbaseClient as _Client` etc.)
# CoinbaseClient is defined above, so imports will succeed.

# End of nija_client.py
