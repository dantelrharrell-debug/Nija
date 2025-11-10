import os
import time
import requests
from loguru import logger
import jwt  # PyJWT required

# ─────────────────────────────────────────────
# 🔐 Environment variables
# ─────────────────────────────────────────────
API_KEY = os.getenv("COINBASE_API_KEY")          # Classic API key (optional fallback)
API_SECRET = os.getenv("COINBASE_API_SECRET")    # Classic API secret
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # For JWT signing

# ─────────────────────────────────────────────
# 🌐 Base URLs
# ─────────────────────────────────────────────
BASE_ADV = "https://api.coinbase.com"            # Advanced API
BASE_CLASSIC = "https://api.cdp.coinbase.com"    # Classic (legacy) API

# ─────────────────────────────────────────────
# ⚙️ NIJA CLIENT
# ─────────────────────────────────────────────
class NijaClient:
    def __init__(self):
        self.jwt = None
        self._init_jwt()

    # 🔸 Initialize JWT (Advanced API)
    def _init_jwt(self):
        if not COINBASE_PEM_CONTENT:
            logger.warning("No PEM content found — skipping JWT setup")
            return

        payload = {
            "sub": "YOUR_CLIENT_ID_OR_EMAIL",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        }

        try:
            self.jwt = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
            logger.info("✅ Generated ephemeral JWT for Advanced API")
        except Exception as e:
            logger.error(f"❌ Failed to generate JWT: {e}")
            self.jwt = None

    # 🔸 Headers for Advanced API
    def _headers_advanced(self):
        return {
            "Authorization": f"Bearer {self.jwt}",
            "CB-VERSION": "2025-11-09",
            "Content-Type": "application/json",
        }

    # 🔸 Headers for Classic API
    def _headers_classic(self):
        return {
            "CB-ACCESS-KEY": API_KEY,
            "CB-ACCESS-SIGN": API_SECRET,  # simplified placeholder
            "CB-VERSION": "2025-11-09",
            "Content-Type": "application/json",
        }

    # 🔸 Fetch accounts (tries Advanced, then Classic)
    def fetch_accounts(self):
        # 1️⃣ Advanced API first
        if self.jwt:
            try:
                url_adv = f"{BASE_ADV.rstrip('/')}/api/v3/brokerage/accounts"
                resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
                if resp.status_code == 200:
                    logger.info("✅ Fetched accounts via Advanced API")
                    return resp.json().get("accounts", resp.json().get("data", []))
                else:
                    logger.warning(f"⚠️ Advanced API failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.warning(f"⚠️ Advanced API exception: {e}")

        # 2️⃣ Classic fallback
        if API_KEY and API_SECRET:
            for attempt in range(3):
                try:
                    url_classic = f"{BASE_CLASSIC.rstrip('/')}/v2/accounts"
                    resp = requests.get(url_classic, headers=self._headers_classic(), timeout=10)
                    if resp.status_code == 200:
                        logger.info("✅ Fetched accounts via Classic API")
                        return resp.json().get("data", [])
                    else:
                        logger.warning(f"⚠️ Classic API attempt {attempt+1} failed: {resp.status_code}")
                except Exception as e:
                    logger.warning(f"⚠️ Classic API attempt {attempt+1} exception: {e}")
                time.sleep(2 ** attempt)

        logger.error("❌ No accounts fetched — both Advanced & Classic failed")
        return []

    # 🔸 Get balances (non-zero only)
    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = []
        for acc in accounts:
            bal = float(acc.get("balance", {}).get("amount", 0))
            if bal > 0:
                balances.append({
                    "id": acc.get("id"),
                    "currency": acc.get("balance", {}).get("currency"),
                    "balance": bal
                })
        if not balances:
            logger.warning("⚠️ No non-zero balances found")
        return balances


# ─────────────────────────────────────────────
# 🧠 Test run
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Starting NIJA client test (LIVE mode)")
    client = NijaClient()

    # Try fetching accounts with retries
    attempts = 3
    for i in range(attempts):
        accounts = client.fetch_accounts()
        if accounts:
            for acc in accounts:
                logger.info(f"Account: {acc}")
            break
        else:
            sleep_time = 2 ** i
            logger.info(f"⏳ Retrying in {sleep_time} seconds (attempt {i+1}/{attempts})")
            time.sleep(sleep_time)
    else:
        logger.error("❌ All retries failed — no accounts fetched")

    # Optional: print balances
    balances = client.get_balances()
    for b in balances:
        logger.info(f"💰 Balance: {b}")
