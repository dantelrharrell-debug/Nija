import os
import time
import hmac
import hashlib
import base64
import json
import logging
import requests

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("❌ Missing Coinbase API credentials.")

        if self.passphrase:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
        else:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
        
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    # ------------------------
    # Core request handler
    # ------------------------
    def _send_request(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}{endpoint}"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2025-11-04"
        }

        timestamp = str(int(time.time()))
        body = json.dumps(data) if data else ""
        message = timestamp + method.upper() + endpoint + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers.update({
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp
        })
        if self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase

        try:
            response = requests.request(method, url, headers=headers, data=body)
            if response.status_code == 401:
                log.error("❌ 401 Unauthorized: Check API key permissions and JWT usage")
                raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
            elif response.status_code >= 400:
                log.error(f"❌ Request failed: {response.status_code} {response.text}")
                raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")

            return response.json()
        except requests.RequestException as e:
            log.error(f"❌ Request exception: {e}")
            raise

    # ------------------------
    # Account Methods
    # ------------------------
    def get_all_accounts(self):
        """Fetch all accounts from Coinbase."""
        return self._send_request("/v2/accounts")["data"]

    def get_usd_spot_balance(self) -> float:
        """Fetch USD balance from Coinbase accounts."""
        accounts = self.get_all_accounts()
        usd_account = next((a for a in accounts if a["currency"] == "USD"), None)
        if usd_account:
            return float(usd_account.get("balance", {}).get("amount", 0))
        return 0.0

# ------------------------
# Utility: Position sizing
# ------------------------
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

# ------------------------
# Preflight check
# ------------------------
def preflight_check():
    log.info("✅ Starting Nija preflight check...")
    client = CoinbaseClient()
    try:
        usd_balance = client.get_usd_spot_balance()
        log.info(f"✅ USD Spot Balance: ${usd_balance:.2f}")
        return True
    except Exception as e:
        log.error(f"❌ Error in Nija preflight: {e}")
        return False

if __name__ == "__main__":
    preflight_check()
