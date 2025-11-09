# nija_client.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import base64
import hmac
import hashlib

# lazy import requests
try:
    import requests
    REQUESTS = True
except Exception:
    requests = None
    REQUESTS = False

def _log(level, *parts):
    try:
        from loguru import logger as _lg
        getattr(_lg, level)(" ".join(map(str, parts)))
    except Exception:
        print(f"[{level.upper()}]", *parts)

class CoinbaseClient:
    def __init__(self,
                 api_key=None,
                 api_secret=None,
                 passphrase=None,
                 org_id=None,
                 base=None,
                 advanced_mode: bool = None):

        # --- Env-backed config ---
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID") or os.getenv("COINBASE_ISS")
        self.custom_base = (base or os.getenv("COINBASE_BASE", "")).strip() or None

        # --- Determine mode ---
        if advanced_mode is not None:
            self.advanced_mode = bool(advanced_mode)
        else:
            m = os.getenv("COINBASE_AUTH_MODE", "").lower()
            if m in ("advanced", "cdp", "jwt"):
                self.advanced_mode = True
            elif m in ("pro", "exchange", "hmac"):
                self.advanced_mode = False
            else:
                self.advanced_mode = bool(self.org_id or os.getenv("COINBASE_PEM_CONTENT"))

        # --- Base URL ---
        if self.custom_base:
            self.base = self.custom_base.rstrip("/")
        else:
            self.base = "https://api.cdp.coinbase.com" if self.advanced_mode else "https://api.exchange.coinbase.com"

        # --- JWT from PEM ---
        self.jwt = os.getenv("COINBASE_JWT") or None
        pem = os.getenv("COINBASE_PEM_CONTENT")
        if not self.jwt and pem:
            try:
                import jwt as _pyjwt
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300}
                iss = os.getenv("COINBASE_ISS") or os.getenv("COINBASE_ORG_ID")
                if iss:
                    payload["iss"] = iss
                token = _pyjwt.encode(payload, pem, algorithm="ES256", headers={"alg":"ES256"})
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                _log("info", "Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                _log("warning", "Failed to generate JWT from PEM:", e)
                self.jwt = None

        _log("info", f"nija_client init: base={self.base} advanced={self.advanced_mode} jwt_set={bool(self.jwt)}")
        print("NIJA-CLIENT-READY: CoinbaseClient (base=%s advanced=%s jwt=%s)" %
              (self.base, self.advanced_mode, bool(self.jwt)))

    # --- Helpers ---
    def _decode_secret(self, s):
        if not s:
            return b""
        try:
            return base64.b64decode(s)
        except Exception:
            return s.encode("utf-8")

    def _hmac_sig(self, ts, method, path, body=""):
        msg = ts + method.upper() + path + (body or "")
        key = self._decode_secret(self.api_secret or "")
        sig = hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("utf-8")

    def _headers_for(self, method, path, body=""):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        ts = str(int(time.time()))
        sig = self._hmac_sig(ts, method, path, body)
        h = {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        if self.passphrase:
            h["CB-ACCESS-PASSPHRASE"] = self.passphrase
        if self.advanced_mode and self.org_id:
            h["CB-ACCESS-ORG"] = self.org_id
        return h

    # --- Fetch accounts (fixed for Advanced JWT) ---
    def fetch_accounts(self):
        if self.advanced_mode and not self.jwt:
            _log("error", "Advanced mode requires JWT (COINBASE_JWT or valid COINBASE_PEM_CONTENT). Returning [].")
            return []

        path = "/accounts"
        url = self.base.rstrip("/") + path
        headers = self._headers_for("GET", path)

        if not REQUESTS:
            _log("error", "requests not available; fetch_accounts returning []")
            return []

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                for key in ("data", "accounts"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                if "currency" in data and ("balance" in data or "available" in data):
                    return [data]
                return []
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            try:
                _log("error", "Error fetching accounts:", e,
                     "status=", getattr(resp, "status_code", None),
                     "url=", url,
                     "body_trunc=", getattr(resp, "text", "")[:800])
            except Exception:
                _log("error", "Error fetching accounts:", e, "url=", url)
            return []

    # --- Aliases ---
    get_accounts = fetch_accounts
    list_accounts = fetch_accounts

    # --- Balances normalized ---
    def get_account_balances(self):
        accs = self.fetch_accounts()
        out = {}
        for a in accs:
            cur = a.get("currency") or a.get("asset")
            amt = None
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                out[cur] = float(amt or 0)
            except Exception:
                try:
                    out[cur] = float(str(amt).replace(",",""))
                except Exception:
                    out[cur] = 0.0
        return out

    get_balances = get_account_balances

# Alias for older code
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
