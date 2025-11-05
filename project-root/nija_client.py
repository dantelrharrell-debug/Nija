import os
import time
import hmac
import hashlib
import requests

class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        # Force HMAC authentication
        if all([self.api_key, self.api_secret, self.passphrase]):
            self.client_type = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient (forced)")
        else:
            raise SystemExit("❌ HMAC credentials missing; cannot use JWT fallback")

    # ===== Fetch accounts via HMAC =====
    def fetch_accounts(self):
        ts = str(int(time.time()))
        method = "GET"
        path = "/accounts"
        message = ts + method + path

        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        r = requests.get(self.base_url + path, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch accounts: {r.status_code} {r.text}")
        return r.json()

    # ===== Get first funded account =====
    def get_funded_account(self, min_balance=1.0):
        accounts = self.fetch_accounts()
        account_list = accounts.get("data", accounts) if isinstance(accounts, dict) else accounts
        for acct in account_list:
            bal_info = acct.get("balance", acct)
            balance = float(bal_info.get("amount", bal_info if isinstance(bal_info, (int,float)) else 0))
            if balance >= min_balance:
                return acct
        raise RuntimeError("❌ No funded account found")


# ===== Quick test =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
    funded = client.get_funded_account(min_balance=1)
    print("✅ Funded account found:", funded)
