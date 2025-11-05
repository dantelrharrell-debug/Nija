import os
import jwt
import requests
import time

# -----------------------------
# PEM Auto-Fix for Advanced JWT
# -----------------------------
def load_pem_from_env(var_name="COINBASE_API_SECRET"):
    pem = os.getenv(var_name)
    if pem is None:
        raise ValueError(f"Environment variable {var_name} is not set.")
    
    # Replace literal "\n" with actual newlines and strip extra whitespace
    pem_fixed = pem.replace("\\n", "\n").strip()
    
    # Ensure proper BEGIN/END framing
    if not pem_fixed.startswith("-----BEGIN EC PRIVATE KEY-----") or not pem_fixed.endswith("-----END EC PRIVATE KEY-----"):
        raise ValueError("PEM content is malformed. Check BEGIN/END lines.")
    
    return pem_fixed

# -----------------------------
# Coinbase Client
# -----------------------------
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Auto-fix PEM if using Advanced JWT
        if self.api_secret and "BEGIN EC PRIVATE KEY" in self.api_secret:
            self.api_secret = load_pem_from_env("COINBASE_API_SECRET")

        # Run preflight check
        self._preflight_check()

    # -----------------------------
    # Preflight check
    # -----------------------------
    def _preflight_check(self):
        print("ℹ️ Running preflight check...")
        try:
            accounts = self.get_all_accounts()
            print(f"✅ Preflight check passed. Accounts fetched: {len(accounts)}")
        except Exception as e:
            print(f"❌ Preflight check failed: {e}")

    # -----------------------------
    # JWT Generator
    # -----------------------------
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

    # -----------------------------
    # Send Request
    # -----------------------------
    def _send_request(self, endpoint, method="GET", body=""):
        headers = {
            "Authorization": f"Bearer {self._generate_jwt(method, endpoint, body)}",
            "Content-Type": "application/json",
        }
        response = requests.request(method, self.base_url + endpoint, headers=headers, data=body)
        if not response.ok:
            raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    # -----------------------------
    # Fetch Accounts
    # -----------------------------
    def get_all_accounts(self):
        try:
            return self._send_request("/v2/accounts")["data"]
        except KeyError:
            raise RuntimeError("❌ Response missing 'data' key. Check API access and PEM formatting.")
        except Exception as e:
            raise RuntimeError(f"❌ Failed to fetch accounts: {e}")

    # -----------------------------
    # Fetch USD Spot Balance
    # -----------------------------
    def get_usd_spot_balance(self):
        try:
            accounts = self.get_all_accounts()
            for acct in accounts:
                if acct.get("currency") == "USD":
                    return float(acct.get("balance", {}).get("amount", 0))
            return 0
        except Exception as e:
            print(f"❌ Warning: Unable to fetch USD balance: {e}")
            return 0

# -----------------------------
# Position Sizing
# -----------------------------
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    raw_allocation = account_equity * (risk_factor / 100)
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size
