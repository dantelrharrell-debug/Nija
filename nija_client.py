import os
import requests
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")


class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # JWT doesn't need this
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase API credentials")

        if not self.passphrase:
            log.warning("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _send_request(self, endpoint, method="GET", data=None):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = self.base_url.rstrip("/") + endpoint

        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers)
            else:
                resp = requests.post(url, headers=headers, json=data)

            if resp.status_code == 401:
                log.error("❌ 401 Unauthorized: Check API key permissions and JWT usage")
                raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")

            if resp.status_code >= 400:
                log.error(f"❌ Request failed: {resp.status_code} {resp.text}")
                raise RuntimeError(f"❌ Request failed: {resp.status_code} {resp.text}")

            return resp.json()

        except requests.RequestException as e:
            log.error(f"❌ Request exception: {e}")
            raise RuntimeError(f"❌ Request exception: {e}")

    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        data = self._send_request(endpoint)
        return data.get("data", [])

    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return float(acc.get("balance", {}).get("amount", 0))
        return 0.0


def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Calculates position size for a trade based on account equity.
    
    account_equity : float : USD account balance
    risk_factor    : float : Multiplier for trade confidence (default=1.0)
    min_percent    : int   : Minimum % of equity to trade
    max_percent    : int   : Maximum % of equity to trade
    
    returns : float : Trade size in USD
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    
    raw_allocation = account_equity * (risk_factor / 100)
    
    # Clamp allocation between min and max percent
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size


# Singleton client for external calls
client = CoinbaseClient()


def get_usd_spot_balance():
    return client.get_usd_spot_balance()


def get_all_accounts():
    return client.get_all_accounts()
