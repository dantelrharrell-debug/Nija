import os
import time
import requests
import jwt
from loguru import logger

class NijaClient:
    def __init__(self):
        # Base URLs
        self.advanced_base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.standard_base = "https://api.coinbase.com"

        # Advanced JWT
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.jwt_token = None
        self._init_jwt()

        # Standard API credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")

        # Start JWT refresh loop if advanced mode is available
        if self.jwt_token:
            self._start_jwt_refresh()

        logger.info(f"NIJA-CLIENT-READY: Advanced JWT set={self.jwt_token is not None}")

    # ------------------- JWT Methods -------------------
    def _init_jwt(self):
        if self.pem and self.iss:
            try:
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": self.iss}
                token = jwt.encode(payload, self.pem, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt_token = token
                logger.info("✅ Generated ephemeral JWT for Advanced API")
            except Exception as e:
                logger.error(f"Failed to generate JWT: {e}")

    def _start_jwt_refresh(self):
        import threading
        def refresh_loop():
            while True:
                time.sleep(240)
                self._init_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    # ------------------- Fetch Accounts -------------------
    def fetch_accounts(self):
        # Try Advanced endpoint first
        if self.jwt_token:
            url = f"{self.advanced_base}/api/v3/brokerage/accounts"
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            try:
                r = requests.get(url, headers=headers, timeout=10)
                logger.info(f"Advanced API status: {r.status_code}")
                if r.status_code == 200:
                    return r.json().get("data", [])
                logger.warning(f"Advanced API failed: {r.status_code} {r.text}")
            except requests.RequestException as e:
                logger.error(f"Advanced API request failed: {e}")

        # Fallback to Standard API if Advanced fails
        if self.api_key and self.api_secret:
            url = f"{self.standard_base}/v2/accounts"
            headers = {"CB-ACCESS-KEY": self.api_key, "Content-Type": "application/json"}
            try:
                r = requests.get(url, headers=headers, timeout=10)
                logger.info(f"Standard API status: {r.status_code}")
                if r.status_code == 200:
                    return r.json().get("data", [])
                logger.warning(f"Standard API failed: {r.status_code} {r.text}")
            except requests.RequestException as e:
                logger.error(f"Standard API request failed: {e}")

        logger.warning("No accounts fetched from either API.")
        return []

    # ------------------- Get Balances -------------------
    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = {}
        for a in accounts:
            currency = a.get("currency") or a.get("asset")
            amt = None
            # Advanced API structure
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            # Standard API structure
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                balances[currency] = float(amt or 0)
            except:
                balances[currency] = 0.0
        return balances


# ------------------- Direct JWT Test -------------------
if __name__ == "__main__":
    pem = os.getenv("COINBASE_PEM_CONTENT")
    iss = os.getenv("COINBASE_ISS")
    base = "https://api.cdp.coinbase.com"

    if pem and iss:
        payload = {"iat": int(time.time()), "exp": int(time.time()) + 300, "iss": iss}
        token = jwt.encode(payload, pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")

        url = f"{base}/api/v3/brokerage/accounts"
        headers = {"Authorization": f"Bearer {token}"}

        r = requests.get(url, headers=headers)
        print("JWT Test Status:", r.status_code)
        print("Response:", r.text)
    else:
        print("Missing COINBASE_PEM_CONTENT or COINBASE_ISS")
