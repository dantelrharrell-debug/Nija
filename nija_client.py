import os
import time
import requests
from loguru import logger
import jwt as pyjwt  # ensure PyJWT is installed

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
                token = pyjwt.encode(payload, pem, algorithm="ES256")
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
            logger.error("Error fetching accounts:", e, "status=", getattr(resp, "status_code", None), "url=", url)
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

# Alias
NijaCoinbaseClient = CoinbaseClient
__all__ = ["CoinbaseClient", "NijaCoinbaseClient"]
