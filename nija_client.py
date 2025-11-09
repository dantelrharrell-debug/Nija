# nija_client.py  (PROJECT ROOT) - Robust CDP / Pro client for Nija
"""
Robust Coinbase client used by start_bot.py.

- Exposes CoinbaseClient and NijaCoinbaseClient (alias).
- Auto-selects Advanced (CDP) vs Pro based on COINBASE_AUTH_MODE or presence of COINBASE_ORG_ID/PEM.
- Supports JWT (COINBASE_JWT or COINBASE_PEM_CONTENT -> ephemeral ES256 if PyJWT available) and HMAC.
- Safe to import (won't crash on missing optional libs).
- Use environment variables to configure:
    COINBASE_AUTH_MODE (advanced|cdp|pro|exchange|hmac)
    COINBASE_API_KEY
    COINBASE_API_SECRET
    COINBASE_API_PASSPHRASE (if needed)
    COINBASE_ORG_ID
    COINBASE_PEM_CONTENT (raw PEM with real newlines)  -- optional
    COINBASE_JWT (optional)
    COINBASE_BASE (optional override)
"""

import os
import time
import hmac
import hashlib
import base64

# Lazy import requests so import doesn't crash if library missing at build time
try:
    import requests
    REQUESTS_AVAILABLE = True
except Exception:
    requests = None
    REQUESTS_AVAILABLE = False

# Optional PyJWT support for PEM -> JWT (only used if env present)
try:
    import jwt as _pyjwt
    PYJWT_AVAILABLE = True
except Exception:
    _pyjwt = None
    PYJWT_AVAILABLE = False

# minimal logging helper (works inside containers)
def _log(level: str, *parts):
    try:
        from loguru import logger as _lg
        getattr(_lg, level)(" ".join(map(str, parts)))
    except Exception:
        print(f"[{level.upper()}]", *parts)

class CoinbaseClient:
    def __init__(self,
                 api_key: str = None,
                 api_secret: str = None,
                 passphrase: str = None,
                 org_id: str = None,
                 base: str = None,
                 advanced_mode: bool = None):
        # read envs if args not provided
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self.custom_base = (base or os.getenv("COINBASE_BASE", "")).strip() or None

        # determine advanced_mode:
        if advanced_mode is not None:
            self.advanced_mode = bool(advanced_mode)
        else:
            mode = os.getenv("COINBASE_AUTH_MODE", "").lower()
            if mode in ("advanced", "cdp", "jwt"):
                self.advanced_mode = True
            elif mode in ("pro", "exchange", "hmac"):
                self.advanced_mode = False
            else:
                # default: assume advanced if org_id or PEM present, otherwise pro
                self.advanced_mode = bool(self.org_id or os.getenv("COINBASE_PEM_CONTENT"))

        # base selection
        if self.custom_base:
            self.base = self.custom_base.rstrip("/")
        else:
            self.base = "https://api.cdp.coinbase.com" if self.advanced_mode else "https://api.exchange.coinbase.com"

        # JWT priority: COINBASE_JWT env or generate from PEM content if present & PyJWT available
        self.jwt = os.getenv("COINBASE_JWT") or None
        pem = os.getenv("COINBASE_PEM_CONTENT")
        if not self.jwt and pem and PYJWT_AVAILABLE:
            try:
                self.jwt = self._jwt_from_pem(pem)
                _log("info", "Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                _log("warning", "Failed to generate JWT from PEM:", e)

        _log("info", "nija_client ready: base=", self.base, "advanced_mode=", self.advanced_mode,
             "jwt_set=", bool(self.jwt), "api_key_set=", bool(self.api_key))

        # visible marker for deploy logs
        try:
            print("NIJA-CLIENT-READY: CoinbaseClient defined (base=%s advanced=%s)" % (self.base, self.advanced_mode))
        except Exception:
            pass

    # Optional: create ephemeral ES256 JWT from raw PEM (COINBASE_PEM_CONTENT)
    def _jwt_from_pem(self, pem_content: str, ttl: int = 300) -> str:
        if not PYJWT_AVAILABLE:
            raise RuntimeError("PyJWT not installed")
        now = int(time.time())
        payload = {"iat": now, "exp": now + int(ttl)}
        iss = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID")
        if iss:
            payload["iss"] = iss
        token = _pyjwt.encode(payload, pem_content, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    # Flexible secret decode: try base64, otherwise raw bytes
    def _decode_secret(self, secret: str) -> bytes:
        if not secret:
            return b""
        s = secret.strip()
        try:
            return base64.b64decode(s)
        except Exception:
            return s.encode("utf-8")

    def _hmac_sig(self, timestamp: str, method: str, path: str, body: str) -> str:
        msg = timestamp + method.upper() + path + (body or "")
        key_bytes = self._decode_secret(self.api_secret or "")
        sig = hmac.new(key_bytes, msg.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("utf-8")

    def _build_headers(self, method: str, path: str, body: str = "") -> dict:
        # If JWT present, use Bearer
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        ts = str(int(time.time()))
        sign = self._hmac_sig(ts, method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sign,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        if self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        # CDP advanced wants org header if org present
        if self.advanced_mode and (self.org_id or os.getenv("COINBASE_ORG_ID")):
            headers["CB-ACCESS-ORG"] = self.org_id or os.getenv("COINBASE_ORG_ID")
        return headers

    def fetch_accounts(self):
        """
        Fetch account list. Uses GET {base}/accounts (CDP and Pro both expose /accounts).
        Normalizes into a list of account dicts.
        Returns [] on any error (safe).
        """
        path = "/accounts"
        url = self.base.rstrip("/") + path
        if not REQUESTS_AVAILABLE:
            _log("error", "requests library unavailable; fetch_accounts returning empty list")
            return []

        try:
            headers = self._build_headers("GET", path, "")
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # normalize common shapes
            if isinstance(data, dict):
                if "accounts" in data and isinstance(data["accounts"], list):
                    return data["accounts"]
                if "data" in data and isinstance(data["data"], list):
                    return data["data"]
                # single object representing account
                if "currency" in data and ("balance" in data or "available" in data):
                    return [data]
                return []
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            try:
                status = getattr(resp, "status_code", None)
                body = getattr(resp, "text", "")[:1000]
                _log("error", "Error fetching accounts:", e, "status=", status, "url=", url, "body_trunc=", body)
            except Exception:
                _log("error", "Error fetching accounts:", e, "url=", url)
            return []

    # Backwards-compat convenience methods
    def get_accounts(self):
        return self.fetch_accounts()

    def list_accounts(self):
        return self.fetch_accounts()

    def get_account_balances(self):
        """
        Returns dict currency -> float(balance). Robust to several account shapes.
        """
        accs = self.fetch_accounts()
        out = {}
        for a in accs:
            cur = a.get("currency") or a.get("asset") or a.get("money_currency")
            amt = None
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                out[cur] = float(amt or 0)
            except Exception:
                try:
                    out[cur] = float(str(amt).replace(",", ""))
                except Exception:
                    out[cur] = 0.0
        return out

    def get_balances(self):
        return self.get_account_balances()

# Alias expected by older code
NijaCoinbaseClient = CoinbaseClient

# explicit exports
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
