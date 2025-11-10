#!/usr/bin/env python3
import os
import time
import requests
import jwt
from loguru import logger
import threading

# ---------------------------
# NijaClient: Basic Advanced Coinbase Client
# ---------------------------
class NijaClient:
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")

        if not all([self.base, self.pem, self.iss]):
            logger.error("Missing COINBASE_BASE, COINBASE_PEM_CONTENT, or COINBASE_ISS")
            raise SystemExit(1)

        self.jwt_token = None
        self._generate_jwt()
        self._start_jwt_refresh()
        logger.info(f"NIJA-CLIENT-READY: base={self.base} jwt_set={self.jwt_token is not None}")

    def _generate_jwt(self):
        now = int(time.time())
        payload = {"iat": now, "exp": now + 300, "iss": self.iss}
        try:
            token = jwt.encode(payload, self.pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt_token = token
            logger.info("✅ JWT generated successfully")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _start_jwt_refresh(self):
        def refresh_loop():
            while True:
                time.sleep(240)
                self._generate_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def fetch_accounts(self):
        if not self.jwt_token:
            logger.warning("JWT not set, cannot fetch accounts")
            return []

        url = f"{self.base}/api/v3/brokerage/accounts"
        headers = {"Authorization": f"Bearer {self.jwt_token}"}

        try:
            r = requests.get(url, headers=headers, timeout=10)
            logger.info(f"Request to {url} returned {r.status_code}")
            if r.status_code == 200:
                return r.json()
            else:
                logger.error(f"Failed to fetch accounts: {r.status_code} {r.text}")
                return []
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        if not accounts:
            logger.warning("No accounts fetched")
            return {}

        balances = {}
        for acc in accounts.get("data", []):
            balances[acc["currency"]] = float(acc.get("balance", 0))
        return balances


# ---------------------------
# CoinbaseClient: Alias / Advanced Wrapper
# ---------------------------
class CoinbaseClient:
    """
    Coinbase Advanced (CDP) client using JWT from PEM/ISS.
    Fetches account balances for live trading.
    """
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.coinbase.com")
        self.advanced_mode = True
        self.jwt = None
        self._init_jwt()
        logger.info(f"nija_client init: base={self.base} advanced={self.advanced_mode} jwt_set={bool(self.jwt)}")
        print(f"NIJA-CLIENT-READY: CoinbaseClient (base={self.base} advanced={self.advanced_mode} jwt={bool(self.jwt)})")

    def _init_jwt(self):
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            try:
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": iss}
                token = jwt.encode(payload, pem, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                logger.error(f"JWT generation failed: {e}")
        else:
            logger.error("Missing COINBASE_PEM_CONTENT or COINBASE_ISS for Advanced JWT")

    def _headers(self):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        return {}

    def fetch_accounts(self):
        """
        Fetch all Coinbase Advanced account balances.
        Returns list of account dicts or [] on failure.
        """
        if not self.jwt:
            logger.error("Advanced mode requires JWT. Returning [].")
            return []

        url = f"{self.base.rstrip('/')}/api/v3/brokerage/accounts"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for key in ("accounts", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            if "currency" in data and ("balance" in data or "available" in data):
                return [data]
            return []
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}, status={getattr(resp, 'status_code', None)}, url={url}")
            return []

    def get_balances(self):
        """
        Returns dict: {currency: balance}
        """
        accounts = self.fetch_accounts()
        out = {}
        for a in accounts:
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


# ---------------------------
# Aliases
# ---------------------------
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient", "NijaClient"]
