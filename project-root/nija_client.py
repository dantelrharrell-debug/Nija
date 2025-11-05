import os
import jwt
import requests
import time

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise RuntimeError("❌ Coinbase API credentials missing in environment variables.")

        # Fix PEM formatting for Advanced Trade API if needed
        if "BEGIN EC PRIVATE KEY" in self.api_secret:
            self.api_secret = self.api_secret.replace("\\n", "\n").strip()

    def _generate_jwt(self, method, endpoint, body=""):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,  # 2-minute expiry
            "method": method.upper(),
            "request_path": endpoint,
            "body": body or ""
        }
        token = jwt.encode(payload, self.api_secret, algorithm="ES256")
        return token

    def _send_request(self, endpoint, method="GET", body=""):
        headers = {
            "Authorization": f"Bearer {self._generate_jwt(method, endpoint, body)}",
            "Content-Type": "application/json",
        }
        response = requests.request(method, self.base_url + endpoint, headers=headers, data=body)
        if not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    def get_all_accounts(self):
        """Fetch all accounts from Coinbase."""
        try:
            return self._send_request("/v2/accounts")["data"]
        except KeyError:
            raise RuntimeError("❌ Response missing 'data'. Check API credentials.")
        except Exception as e:
            raise RuntimeError(f"❌ Failed to fetch accounts: {e}")

    def get_funded_account(self, preferred_currency="USD"):
        """
        Automatically pick the first account with a balance > 0.
        Prioritize 'preferred_currency'.
        """
        accounts = self.get_all_accounts()
        # Try preferred currency first
        for acct in accounts:
            amount = float(acct.get("balance", {}).get("amount", 0))
            if acct.get("currency") == preferred_currency and amount > 0:
                return acct
        # If preferred not funded, pick first account with funds
        for acct in accounts:
            amount = float(acct.get("balance", {}).get("amount", 0))
            if amount > 0:
                return acct
        return None  # no funded accounts

    def get_usd_spot_balance(self):
        """Return USD balance or 0."""
        acct = self.get_funded_account(preferred_currency="USD")
        if acct:
            return float(acct.get("balance", {}).get("amount", 0))
        return 0

# Position sizing helper
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    return max(min_alloc, min(raw_allocation, max_alloc))
