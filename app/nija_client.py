# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests

# ---------- DEBUG ENV (drop at top for 1 deploy only) ----------
def mask(v, keep=4):
    if v is None:
        return None
    s = str(v)
    if len(s) <= keep*2:
        return s[:keep] + "..." + s[-keep:]
    return s[:keep] + "..." + s[-keep:]

print("DEBUG ENV - COINBASE_API_KEY:", mask(os.getenv("COINBASE_API_KEY")))
print("DEBUG ENV - COINBASE_API_SECRET (masked):", mask(os.getenv("COINBASE_API_SECRET")))
print("DEBUG ENV - COINBASE_PASSPHRASE:", mask(os.getenv("COINBASE_PASSPHRASE")))
print("DEBUG ENV - COINBASE_API_BASE:", mask(os.getenv("COINBASE_API_BASE")))

# Fail fast so logs clearly show missing envs
if not all([os.getenv("COINBASE_API_KEY"), os.getenv("COINBASE_API_SECRET"), os.getenv("COINBASE_PASSPHRASE")]):
    raise SystemExit("DEBUG: One or more Coinbase HMAC env vars are missing or empty.")
# ---------- end debug ----------


class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        # Validate credentials (should be present because debug check ran)
        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise SystemExit("❌ HMAC credentials missing; cannot use JWT fallback")
        print("✅ Using HMAC authentication for CoinbaseClient (forced)")

        # Fetch funded account immediately (non-fatal)
        try:
            funded = self.get_funded_account(min_balance=1)
            print("✅ Funded account found on startup:", funded)
        except Exception as e:
            print(f"❌ Failed to fetch funded account on startup: {e}")

    # ===== Internal: Build headers =====
    def _get_headers(self, method, path, body=""):
        ts = str(int(time.time()))
        message = ts + method + path + body

        # Coinbase requires base64-decoded secret for HMAC
        secret_bytes = base64.b64decode(self.api_secret)

        signature = hmac.new(
            secret_bytes,
            message.encode("utf-8"),
            hashlib.sha256
        ).digest()

        signature_b64 = base64.b64encode(signature).decode()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        return headers

    # ===== Fetch accounts via HMAC =====
    def fetch_accounts(self):
        path = "/accounts"
        method = "GET"
        body = ""  # GET requests have empty body
        headers = self._get_headers(method, path, body)
        url = self.base_url + path
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch accounts: {r.status_code} {r.text}")
        return r.json()

    # ===== Get first funded account =====
    def get_funded_account(self, min_balance=1.0):
        accounts = self.fetch_accounts()
        account_list = accounts.get("data", accounts) if isinstance(accounts, dict) else accounts
        for acct in account_list:
            bal_info = acct.get("balance", acct)
            balance = float(bal_info.get("amount", bal_info if isinstance(bal_info, (int, float)) else 0))
            if balance >= min_balance:
                return acct
        raise RuntimeError("❌ No funded account found")


# ===== Quick test / live-ready instantiation =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
