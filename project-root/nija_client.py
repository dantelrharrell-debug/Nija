# nija_client.py
import os
import time
import hmac
import hashlib
import requests
from typing import List, Optional

# Coinbase Advanced / CDP default base
DEFAULT_CDP_BASE = "https://api.cdp.coinbase.com/platform/v2"

class CoinbaseClient:
    """
    Minimal Coinbase Advanced (CDP) client.
    Uses HMAC-SHA256 signing with API secret for endpoint auth.
    Passphrase is optional/ignored for Advanced API.
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Optional: legacy passphrase (ignored for CDP)
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)

        self.base_url = os.getenv("COINBASE_API_BASE", DEFAULT_CDP_BASE).rstrip("/")
        # Ensure base_url path ends where we expect; default includes /platform/v2

        if not self.api_key or not self.api_secret:
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment variables")

        if not self.api_passphrase:
            # explicit info only
            print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        """
        Create authentication headers expected by Coinbase CDP HMAC flow.
        NOTE: CDP may expect different header names — this mirrors what worked in your logs.
        """
        timestamp = str(int(time.time()))
        method = method.upper()
        # path should begin with '/'
        if not path.startswith("/"):
            path = "/" + path
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        # Only include passphrase if explicitly present (for legacy compatibility)
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase
        return headers

    def list_accounts(self) -> List[dict]:
        """
        List accounts from Coinbase Advanced API.
        Returns list (possibly empty) or raises requests.HTTPError for unexpected errors.
        """
        path = "/accounts"
        url = f"{self.base_url}{path}"
        headers = self._sign("GET", path)
        resp = requests.get(url, headers=headers, timeout=10)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            # For clarity in logs, re-raise after logging
            print(f"Error fetching accounts: {resp.status_code} {resp.text}")
            raise
        data = resp.json()
        # CDP responses often place data under "data" key
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        # fallback: return raw json if structure differs
        return data

# small helper used by other parts of project (some logs complained about missing calculate_position_size)
def calculate_position_size(account_balance: float, risk_per_trade: float, entry_price: float, stop_loss: float) -> float:
    """
    Basic position sizing helper:
      - risk_per_trade: fraction of balance to risk (e.g., 0.02 for 2%)
      - returns number of units/contracts (not USD)
    """
    if account_balance <= 0 or entry_price == stop_loss:
        raise ValueError("Invalid inputs for position sizing")
    risk_amount = account_balance * float(risk_per_trade)
    position_size = risk_amount / abs(float(entry_price) - float(stop_loss))
    return position_size
