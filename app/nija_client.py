import os
import requests

# ----------------------------
# Coinbase Classic Client
# ----------------------------
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise RuntimeError("❌ Coinbase API credentials missing in environment variables.")

        # Classic mode active
        self.mode = "classic"
        print("INFO: CoinbaseClient initialized (classic mode)")

    def _headers(self):
        """Return headers for classic API key mode."""
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,  # For classic API, pass as signature placeholder
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def get_all_accounts(self):
        """Fetch all accounts from Coinbase."""
        try:
            url = f"{self.base_url}/v2/accounts"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 401:
                raise RuntimeError(f"❌ 401 Unauthorized: Check API key + permissions")
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            raise RuntimeError(f"❌ Failed to fetch all accounts: {e}")

    def get_usd_spot_balance(self):
        """Fetch USD balance. Returns 0 if not found."""
        try:
            accounts = self.get_all_accounts()
            for acct in accounts:
                if acct.get("currency") == "USD":
                    return float(acct.get("balance", {}).get("amount", 0))
            return 0.0
        except Exception as e:
            print(f"❌ Warning: Unable to fetch USD balance: {e}")
            return 0.0


# ----------------------------
# Position sizing utility
# ----------------------------
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Returns trade size in USD.
    - account_equity: USD available
    - risk_factor: percentage of equity to risk (1% = 1.0)
    - min_percent/max_percent: bounds for position sizing
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be > 0 to trade.")

    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)

    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size


# ----------------------------
# Exported for nija_debug.py
# ----------------------------
get_all_accounts = CoinbaseClient().get_all_accounts
get_usd_spot_balance = CoinbaseClient().get_usd_spot_balance
