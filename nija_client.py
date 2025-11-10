import os
import time
import requests
import jwt
from loguru import logger

# ===========================
# CONFIG
# ===========================
BASE_ADVANCED = "https://api.cdp.coinbase.com"  # Advanced API base
BASE_CLASSIC = "https://api.coinbase.com"       # Classic API base
JWT_REFRESH_INTERVAL = 240  # seconds

COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ISS = os.getenv("COINBASE_ISS")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")


# ===========================
# Nija Client
# ===========================
class NijaClient:
    def __init__(self):
        self.base_advanced = BASE_ADVANCED
        self.base_classic = BASE_CLASSIC
        self.jwt = None
        self.api_key = COINBASE_API_KEY
        self.api_secret = COINBASE_API_SECRET
        self.working_api = None
        self._init_jwt()
        logger.info(f"NIJA-CLIENT-READY: base={self.base_advanced} jwt_set={self.jwt is not None}")

    # ---------------------------
    # JWT (for Advanced API, optional)
    # ---------------------------
    def _init_jwt(self):
        if COINBASE_PEM_CONTENT and COINBASE_ISS:
            payload = {"iat": int(time.time()), "exp": int(time.time()) + 300, "iss": COINBASE_ISS}
            self.jwt = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
            if isinstance(self.jwt, bytes):
                self.jwt = self.jwt.decode("utf-8")
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            # start auto-refresh
            self._start_jwt_refresh()
        else:
            logger.warning("No PEM/ISS for Advanced API; skipping JWT setup")

    def _start_jwt_refresh(self):
        def refresh_loop():
            while True:
                try:
                    payload = {"iat": int(time.time()), "exp": int(time.time()) + 300, "iss": COINBASE_ISS}
                    self.jwt = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
                    if isinstance(self.jwt, bytes):
                        self.jwt = self.jwt.decode("utf-8")
                    logger.debug("JWT refreshed")
                except Exception as e:
                    logger.error(f"JWT refresh failed: {e}")
                time.sleep(JWT_REFRESH_INTERVAL)
        import threading
        t = threading.Thread(target=refresh_loop, daemon=True)
        t.start()

    # ---------------------------
    # Headers
    # ---------------------------
    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}"}

    def _headers_classic(self):
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,  # Note: Proper HMAC generation required in live trading
            "CB-ACCESS-TIMESTAMP": str(int(time.time())),
            "Content-Type": "application/json"
        }

    # ---------------------------
    # Fetch accounts
    # ---------------------------
    def fetch_accounts(self):
        # -----------------------
        # Skip Advanced if unsupported
        # -----------------------
        if self.jwt:
            try:
                url_adv = f"{self.base_advanced.rstrip('/')}/api/v3/brokerage/accounts"
                resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
                if resp.status_code == 200:
                    logger.info("Fetched accounts from Advanced API")
                    self.working_api = "advanced"
                    return resp.json().get("accounts", resp.json().get("data", []))
                else:
                    logger.warning(f"Advanced API failed ({resp.status_code}), switching to Classic API")
            except Exception as e:
                logger.warning(f"Advanced API exception: {e}, switching to Classic API")

        # -----------------------
        # Classic API with retries
        # -----------------------
        if self.api_key and self.api_secret:
            for attempt in range(3):
                try:
                    url_classic = f"{self.base_classic.rstrip('/')}/v2/accounts"
                    resp = requests.get(url_classic, headers=self._headers_classic(), timeout=10)
                    if resp.status_code == 200:
                        logger.info("Fetched accounts from Classic API")
                        self.working_api = "classic"
                        return resp.json().get("data", [])
                    else:
                        logger.warning(f"Classic API attempt {attempt+1} failed: {resp.status_code}")
                except Exception as e:
                    logger.warning(f"Classic API attempt {attempt+1} exception: {e}")
                time.sleep(2 ** attempt)  # exponential backoff

        logger.error("No accounts fetched — both Advanced and Classic failed")
        return []

    # ---------------------------
    # Get balances
    # ---------------------------
    def get_balances(self):
        accounts = self.fetch_accounts()
        if not accounts:
            logger.warning("No accounts found")
            return {}
        balances = {}
        for acct in accounts:
            balances[acct.get("currency", acct.get("id", "UNKNOWN"))] = float(acct.get("balance", {}).get("amount", 0))
        non_zero = {k: v for k, v in balances.items() if v != 0}
        if not non_zero:
            logger.warning("No non-zero balances found")
        return non_zero


# ===========================
# RUN BOT
# ===========================
if __name__ == "__main__":
    logger.info("Starting Nija bot — LIVE mode")
    nija = NijaClient()
    balances = nija.get_balances()
    logger.info(f"Current balances: {balances}")
