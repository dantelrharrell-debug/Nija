#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import base64
import hmac
import hashlib
import requests
from loguru import logger

# Lazy logger fallback
def _log(level, *parts):
    try:
        getattr(logger, level)(" ".join(map(str, parts)))
    except Exception:
        print(f"[{level.upper()}]", *parts)

REQUESTS = True

class CoinbaseClient:
    """
    Coinbase Advanced (CDP) client using JWT from PEM/ISS
    Fetches account balances for live trading
    """
    def __init__(self):
        # Base and Advanced Mode
        self.base = "https://api.coinbase.com"
        self.advanced_mode = True

        # JWT generation
        self.jwt = None
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            try:
                import jwt as pyjwt
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": iss}
                token = pyjwt.encode(payload, pem, algorithm="ES256", headers={"alg":"ES256"})
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                _log("info", "Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                _log("error", "JWT generation failed:", e)
                self.jwt = None
        else:
            _log("error", "Missing COINBASE_PEM_CONTENT or COINBASE_ISS for Advanced JWT")

        _log("info", f"nija_client init: base={self.base} advanced={self.advanced_mode} jwt_set={bool(self.jwt)}")
        print(f"NIJA-CLIENT-READY: CoinbaseClient (base={self.base} advanced={self.advanced_mode} jwt={bool(self.jwt)})")

    def _headers_for(self, method, path, body=""):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        return {}

    def fetch_accounts(self):
        """
        Fetch all Coinbase Advanced account balances
        Returns list of account dicts or [] on failure
        """
        if not self.jwt:
            _log("error", "Advanced mode requires JWT. Returning [].")
            return []

        path = "/api/v3/brokerage/accounts"
        url = self.base.rstrip("/") + path
        headers = self._headers_for("GET", path)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # Normalize: v3 returns {"accounts": [...] } or {"data": [...]}
            for key in ("accounts", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Single account dict fallback
            if "currency" in data and ("balance" in data or "available" in data):
                return [data]
            return []
        except Exception as e:
            _log("error", "Error fetching accounts:", e, "status=", getattr(resp, "status_code", None), "url=", url)
            return []

    def get_balances(self):
        """
        Returns dict: {currency: balance}
        """
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
            except:
                out[cur] = 0.0
        return out

# Alias
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
