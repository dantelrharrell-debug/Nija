import os
import stat
import time
import hmac
import hashlib
import requests
import jwt

# ===== Write PEM from environment if present =====
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if pem_content:
    pem_content = pem_content.replace("\\n", "\n")  # convert literal \n to real newlines
    with open("coinbase.pem", "w") as f:
        f.write(pem_content)
    os.chmod("coinbase.pem", 0o600)  # secure permissions

# ===== Coinbase Client Wrapper =====
class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        # JWT/PEM credentials
        self.pem_path = "coinbase.pem" if pem_content else None
        self.iss = os.getenv("COINBASE_ISS")

        if self.api_key and self.api_secret and self.passphrase:
            self.client_type = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient")
        elif self.pem_path:
            self.client_type = "JWT"
            print("✅ Using JWT/PEM authentication for CoinbaseClient")
        else:
            raise SystemExit(
                "❌ Missing credentials: set either COINBASE_API_KEY/SECRET/PASSPHRASE or COINBASE_PEM_CONTENT"
            )

    # ===== Fetch all accounts =====
    def fetch_accounts(self):
        if self.client_type == "HMAC":
            return self._fetch_accounts_hmac()
        elif self.client_type == "JWT":
            return self._fetch_accounts_jwt()
        else:
            raise RuntimeError("Unknown client type")

    # ===== HMAC fetch =====
    def _fetch_accounts_hmac(self):
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

    # ===== JWT fetch =====
    def _fetch_accounts_jwt(self):
        now = int(time.time())
        payload = {"iat": now}
        if self.iss:
            payload["iss"] = self.iss
        with open(self.pem_path, "rb") as f:
            private_key = f.read()
        token = jwt.encode(payload, private_key, algorithm="RS256")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = "https://api.coinbase.com/v2/accounts"
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch accounts (JWT): {r.status_code} {r.text}")
        return r.json()

    # ===== Find first funded account =====
    def get_funded_account(self, min_balance=1.0):
        """
        Returns the first account with balance >= min_balance
        """
        accounts = self.fetch_accounts()
        # JWT returns 'data', HMAC might return list directly
        account_list = accounts.get("data", accounts) if isinstance(accounts, dict) else accounts
        for acct in account_list:
            # handle balance field for JWT vs HMAC
            bal_info = acct.get("balance", acct)
            balance = float(bal_info.get("amount", bal_info if isinstance(bal_info, (int,float)) else 0))
            currency = bal_info.get("currency", acct.get("currency", "USD"))
            if balance >= min_balance:
                return acct
        raise RuntimeError("❌ No funded account found")

# ===== Quick test =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
    funded = client.get_funded_account(min_balance=1)
    print("✅ Funded account found:", funded)
