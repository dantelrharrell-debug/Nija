# nija_client.py (updated)

import os
import time
import jwt
import requests
import logging

log = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")  # Advanced JWT private key
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        
        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase Advanced JWT credentials in environment.")
        
        log.info("⚠️ No passphrase required for Advanced JWT keys.")
        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")
        
        # Run preflight
        self._preflight_check()
    
    def _generate_jwt(self, method="GET", endpoint="/v2/accounts", body=None):
        timestamp = int(time.time())
        body_str = body if body else ""
        payload = {
            "iat": timestamp,
            "exp": timestamp + 60,
            "sub": self.api_key,
            "path": endpoint,
            "method": method,
            "body": body_str
        }
        token = jwt.encode(payload, self.api_secret, algorithm="ES256")
        return token
    
    def _send_request(self, endpoint, method="GET", body=None):
        url = self.base_url + endpoint
        token = self._generate_jwt(method, endpoint, body)
        headers = {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-11-04"
        }
        response = requests.request(method, url, headers=headers, data=body)
        if response.status_code == 401:
            log.error("❌ 401 Unauthorized: Check API key permissions and JWT usage")
            raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
        elif response.status_code >= 400:
            log.error(f"❌ Request failed: {response.status_code} {response.text}")
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()
    
    def _preflight_check(self):
        """
        Check if the JWT key has wallet:accounts:read permission
        """
        log.info("ℹ️ Running preflight check...")
        try:
            accounts = self.get_all_accounts()
            log.info(f"✅ Preflight check passed. Found {len(accounts)} accounts.")
        except RuntimeError as e:
            log.error("❌ Preflight failed. Your JWT key may be missing required permissions.")
            self.list_jwt_permissions()
            raise e

    def list_jwt_permissions(self):
        """
        Inspect the JWT payload for permissions.
        Note: Coinbase JWT keys encode allowed scopes. This is a static check.
        """
        try:
            payload = jwt.decode(self.api_secret, options={"verify_signature": False})
            log.info(f"ℹ️ JWT payload (decoded, no verification): {payload}")
            if "permissions" in payload:
                log.info(f"✅ JWT permissions: {payload['permissions']}")
            else:
                log.warning("⚠️ No 'permissions' field found in JWT payload.")
        except Exception as e:
            log.error(f"❌ Failed to decode JWT: {e}")
    
    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        data = self._send_request(endpoint)
        return data.get("data", [])
    
    def get_usd_spot_balance(self):
        accounts = self.get_all_accounts()
        for acct in accounts:
            if acct["currency"] == "USD":
                return float(acct["balance"]["amount"])
        log.error("❌ USD account not found.")
        raise RuntimeError("❌ USD account not found.")

# Utility function for position sizing
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    
    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size

# Convenience helpers
_client = CoinbaseClient()

def get_usd_spot_balance():
    return _client.get_usd_spot_balance()

def get_all_accounts():
    return _client.get_all_accounts()
