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

        # Automatically fix PEM formatting for Advanced JWT
        if self.api_secret and "BEGIN EC PRIVATE KEY" in self.api_secret:
            self.api_secret = self.api_secret.replace("\\n", "\n").strip()

        # Preflight check
        self._preflight_check()

    def _preflight_check(self):
        print("ℹ️ Running preflight check...")
        try:
            accounts = self.get_all_accounts()
            print(f"✅ Preflight check passed. Accounts fetched: {len(accounts)}")
        except Exception as e:
            print(f"❌ Preflight check failed: {e}")

    def _generate_jwt(self, method, endpoint, body=""):
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
        headers = {
            "Authorization": f"Bearer {self._generate_jwt(method, endpoint, body)}",
            "Content-Type": "application/json",
        }
        response = requests.request(method, self.base_url + endpoint, headers=headers, data=body)
        if not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    def get_all_accounts(self):
        try:
            return self._send_request("/v2/accounts")["data"]
        except KeyError:
            raise RuntimeError("❌ Response missing 'data' key. Check API access and PEM formatting.")
        except Exception as e:
            raise RuntimeError(f"❌ Failed to fetch accounts: {e}")

    def get_usd_spot_balance(self):
        """Fetch USD balance. Returns 0 if fetch fails."""
        try:
            accounts = self.get_all_accounts()
            for acct in accounts:
                if acct.get("currency") == "USD":
                    return float(acct.get("balance", {}).get("amount", 0))
            return 0
        except Exception as e:
            print(f"❌ Warning: Unable to fetch USD balance: {e}")
            return 0


# Position sizing function
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size
