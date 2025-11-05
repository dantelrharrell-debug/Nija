import os
import time
import logging
import jwt
import requests

LOG = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s")


class CoinbaseClient:
    def __init__(self):
        LOG.info("🔍 Checking Coinbase credentials in environment...")

        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret_raw = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret_raw:
            raise RuntimeError("❌ Missing Coinbase API credentials (key or secret).")

        # Allow user to force auth mode via env
        forced_mode = os.getenv("COINBASE_AUTH_MODE", "").lower().strip()
        if forced_mode not in ("advanced", "classic", ""):
            LOG.warning("COINBASE_AUTH_MODE value '%s' not recognized. Falling back to auto-detect.", forced_mode)
            forced_mode = ""

        # Auto-fix PEM formatting if Advanced key is used
        if "BEGIN EC PRIVATE KEY" in self.api_secret_raw or "\\n" in self.api_secret_raw:
            self.api_secret_raw = self.api_secret_raw.replace("\\n", "\n").strip()

        # Determine auth mode
        if forced_mode == "advanced":
            self.auth_mode = "advanced"
        elif forced_mode == "classic":
            self.auth_mode = "classic"
        else:
            self.auth_mode = self._detect_auth_mode()

        LOG.info("✅ CoinbaseClient initialized (%s mode).", self.auth_mode.title())

        # Run preflight check
        LOG.info("ℹ️ Running preflight check...")
        try:
            _ = self.get_all_accounts()
            LOG.info("✅ Preflight check passed — Coinbase API connection good.")
        except Exception as e:
            LOG.warning("❌ Preflight check failed: %s", e)
            if "401" in str(e):
                LOG.warning("⚠️ Classic mode active but full request-signing not implemented. This may cause 401.")

    # Detect mode based on secret pattern
    def _detect_auth_mode(self):
        if "BEGIN EC PRIVATE KEY" in self.api_secret_raw:
            return "advanced"
        return "classic"

    # === JWT Auth (Advanced Trade API) ===
    def _generate_jwt(self, method, endpoint, body=""):
        if not self.api_secret_raw:
            raise RuntimeError("❌ Missing PEM secret for JWT generation.")

        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,  # 2 minutes expiry
            "method": method.upper(),
            "request_path": endpoint,
            "body": body or ""
        }
        token = jwt.encode(payload, self.api_secret_raw, algorithm="ES256")
        return token

    def _headers(self, method, endpoint, body=""):
        if self.auth_mode == "advanced":
            token = self._generate_jwt(method, endpoint, body)
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        else:
            # Classic fallback — missing full HMAC signing
            return {
                "CB-ACCESS-KEY": self.api_key,
                "CB-VERSION": "2021-05-24",
                "Content-Type": "application/json",
            }

    def _send_request(self, endpoint, method="GET", body=""):
        headers = self._headers(method, endpoint, body)
        url = self.base_url + endpoint

        response = requests.request(method, url, headers=headers, data=body)
        if not response.ok:
            raise RuntimeError(f"❌ {response.status_code} {response.reason}: {response.text}")
        return response.json()

    # === Public / Account Methods ===
    def get_all_accounts(self):
        try:
            data = self._send_request("/v2/accounts")
            if "data" not in data:
                raise RuntimeError("Response missing 'data' key.")
            return data["data"]
        except Exception as e:
            raise RuntimeError(f"❌ Failed to fetch all accounts: {e}")

    def get_usd_spot_balance(self):
        try:
            accounts = self.get_all_accounts()
            for acct in accounts:
                if acct.get("currency") == "USD":
                    return float(acct.get("balance", {}).get("amount", 0))
            return 0.0
        except Exception as e:
            LOG.error("❌ Failed to fetch USD Spot balance: %s", e)
            return 0.0


# === Position Sizing ===
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")

    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)

    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size
