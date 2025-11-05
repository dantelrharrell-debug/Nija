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

        # Automatically fix PEM formatting if using Advanced JWT
        if self.api_secret and "BEGIN EC PRIVATE KEY" in self.api_secret:
            self.api_secret = self.api_secret.replace("\\n", "\n").strip()

        # Run preflight check
        self._preflight_check()

    def _preflight_check(self):
        print("ℹ️ Running preflight check...")
        try:
            accounts = self.get_all_accounts()
            usd_balance = self.get_usd_spot_balance()
            print(f"✅ Preflight check passed. {len(accounts)} accounts found. USD balance: {usd_balance}")
        except Exception as e:
            print("❌ Preflight check failed:", str(e))

    def _generate_jwt(self, method, endpoint, body=""):
        """Generate JWT token for Advanced JWT key"""
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "method": method.upper(),
            "request_path": endpoint,
            "body": body or ""
        }
        token = jwt.encode(payload, self.api_secret, algorithm="ES256")
        return token

    def _send_request(self, endpoint, method="GET", body=""):
        """Send authenticated request to Coinbase API"""
        headers = {
            "Authorization": f"Bearer {self._generate_jwt(method, endpoint, body)}",
            "Content-Type": "application/json",
        }
        response = requests.request(method, self.base_url + endpoint, headers=headers, data=body)
        if not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    def get_all_accounts(self):
        """Return all Coinbase accounts"""
        return self._send_request("/v2/accounts")["data"]

    def get_usd_spot_balance(self):
        """Return USD account balance"""
        accounts = self.get_all_accounts()
        for acct in accounts:
            if acct['currency'] == 'USD':
                return float(acct['balance']['amount'])
        raise RuntimeError("No USD account found")

# Optional: Position sizing function
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Calculates trade size based on account equity.

    account_equity : float : USD account balance
    risk_factor    : float : Confidence multiplier (default=1.0)
    min_percent    : int   : Minimum % of equity to trade
    max_percent    : int   : Maximum % of equity to trade
    returns        : float : Trade size in USD
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size
