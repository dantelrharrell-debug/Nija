import os
import requests
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")  # JWT or classic secret
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Optional
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Coinbase API credentials missing in environment.")

        if self.passphrase is None:
            log.warning("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        else:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _send_request(self, endpoint, method="GET", payload=None, use_jwt=True):
        url = self.base_url + endpoint
        headers = {"Content-Type": "application/json"}

        if use_jwt:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        else:
            headers.update({
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "CB-ACCESS-TIMESTAMP": str(int(os.time.time())),
                "CB-ACCESS-SIGN": ""  # For classic API, generate if trading
            })

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=payload)
            else:
                raise RuntimeError(f"❌ Unsupported HTTP method: {method}")

            if response.status_code == 401:
                raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
            elif response.status_code == 404:
                raise RuntimeError(f"❌ 404 Not Found: {endpoint}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"❌ Request exception: {e}")
            raise

    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        return self._send_request(endpoint)["data"]

    def get_usd_spot_balance(self):
        accounts_data = self.get_all_accounts()
        for acct in accounts_data:
            if acct["currency"] == "USD":
                return float(acct["balance"]["amount"])
        return 0.0

    def validate_jwt(self):
        try:
            self._send_request("/v2/accounts")
            log.info("✅ JWT valid!")
            return True
        except RuntimeError as e:
            log.error(f"❌ JWT validation failed: {e}")
            return False


# --- Helper function ---
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Calculates position size for a trade based on account equity.
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")

    raw_allocation = account_equity * (risk_factor / 100)

    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)

    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size
