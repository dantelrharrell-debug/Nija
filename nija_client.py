import os
import time
import requests
import jwt as pyjwt
from loguru import logger

class NijaCoinbaseClient:
    def __init__(self):
        # Detect which API mode to use
        self.base = os.getenv("COINBASE_BASE")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

        self.advanced_mode = False
        self.jwt_token = None

        if self.pem and self.iss:
            self.advanced_mode = True
            self.base = self.base or "https://api.cdp.coinbase.com"
            self._init_jwt()
            logger.info("Using Coinbase Advanced (CDP) mode")
        elif self.api_key and self.api_secret:
            self.advanced_mode = False
            self.base = self.base or "https://api.coinbase.com"
            logger.info("Using Standard Coinbase API mode")
        else:
            logger.error("No valid Coinbase credentials found")
            raise SystemExit(1)

        logger.info(f"NIJA-CLIENT-READY: base={self.base} advanced={self.advanced_mode}")

    # -------------------- Advanced JWT --------------------
    def _init_jwt(self):
        try:
            now = int(time.time())
            payload = {"iat": now, "exp": now + 300, "iss": self.iss}
            token = pyjwt.encode(payload, self.pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt_token = token
            logger.info("✅ JWT generated successfully")
        except Exception as e:
            logger.error(f"JWT generation failed: {e}")
            raise

    def _refresh_jwt_loop(self):
        import threading
        def refresh():
            while True:
                time.sleep(240)
                self._init_jwt()
        threading.Thread(target=refresh, daemon=True).start()

    def _headers(self):
        if self.advanced_mode:
            return {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        else:
            return {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": self.api_secret,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json"
            }

    # -------------------- Fetch Accounts --------------------
    def fetch_accounts(self):
        if self.advanced_mode:
            url = f"{self.base.rstrip('/')}/api/v3/brokerage/accounts"
        else:
            url = f"{self.base.rstrip('/')}/v2/accounts"

        try:
            r = requests.get(url, headers=self._headers(), timeout=15)
            r.raise_for_status()
            data = r.json()
            # Advanced API returns 'data' or 'accounts'
            if self.advanced_mode:
                return data.get("data") or data.get("accounts") or []
            else:
                return data.get("data") or []
        except Exception as e:
            logger.error(f"Error fetching accounts: {e} | status={getattr(r, 'status_code', None)} | url={url}")
            return []

    # -------------------- Get Balances --------------------
    def get_balances(self):
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
