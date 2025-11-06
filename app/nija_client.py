print("DBG ENV:", {k: os.getenv(k) for k in ["COINBASE_API_KEY","COINBASE_API_SECRET","COINBASE_PASSPHRASE"]})

# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests

# ---------- DEBUG ENV (paste at top for 1 deploy only) ----------
def mask(v, keep=4):
    if v is None: return None
    s = str(v)
    if len(s) <= keep*2: return s[:keep] + "..." + s[-keep:]
    return s[:keep] + "..." + s[-keep:]

keys = sorted([k for k in os.environ.keys() if k.upper().startswith("COINBASE")])
print("DBG KEYS:", keys)
print("DBG - COINBASE_API_KEY:", mask(os.getenv("COINBASE_API_KEY")))
print("DBG - COINBASE_API_SECRET:", mask(os.getenv("COINBASE_API_SECRET")))
print("DBG - COINBASE_PASSPHRASE:", mask(os.getenv("COINBASE_PASSPHRASE")))
print("DBG - COINBASE_API_BASE:", mask(os.getenv("COINBASE_API_BASE")))

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

        # Validate credentials
        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise SystemExit("❌ HMAC credentials missing; cannot use JWT fallback")
        print("✅ Using HMAC authentication for CoinbaseClient (forced)")

        # Optional: fetch funded account immediately (non-fatal)
        try:
            funded = self.get_funded_account(min_balance=1)
            print("✅ Funded account found on startup:", funded)
        except Exception as e:
            print(f"❌ Failed to fetch funded account on startup: {e}")

    # ===== Internal: Build HMAC headers =====
    def _get_headers(self, method, path, body=""):
        ts = str(int(time.time()))
        message = ts + method + path + body
        secret_bytes = base64.b64decode(self.api_secret)
        signature = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        return headers

    # ===== Fetch accounts via HMAC with debug =====
    def fetch_accounts(self):
        path = "/accounts"
        method = "GET"
        body = ""
        headers = self._get_headers(method, path, body)
        url = self.base_url + path

        # Debug: show signing info
        ts = headers.get("CB-ACCESS-TIMESTAMP")
        print("DEBUG SIGNING -> ts:", ts, "method:", method, "path:", path, "body_len:", len(body))
        print("DEBUG KEY (masked):", (self.api_key[:4] + "..." + self.api_key[-4:]) if self.api_key else None)
        print("DEBUG HEADERS (no secret):", {k: headers[k] for k in headers if k != "CB-ACCESS-SIGN"})

        r = requests.get(url, headers=headers, timeout=15)
        print("DEBUG HTTP STATUS:", r.status_code)
        print("DEBUG HTTP BODY:", r.text)

        if r.status_code == 401:
            raise RuntimeError("❌ Coinbase API Unauthorized (401). Check API key and permissions.")
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch accounts: {r.status_code} {r.text}")

        return r.json()

    # ===== Fetch all Coinbase wallets via CDP API =====
    def fetch_all_wallets(self):
        path = "/accounts"
        method = "GET"
        body = ""
        headers = self._get_headers(method, path, body)
        url = self.base_url + path

        ts = headers.get("CB-ACCESS-TIMESTAMP")
        print("DEBUG SIGNING -> ts:", ts, "method:", method, "path:", path, "body_len:", len(body))
        print("DEBUG KEY (masked):", (self.api_key[:4] + "..." + self.api_key[-4:]) if self.api_key else None)
        print("DEBUG HEADERS (no secret):", {k: headers[k] for k in headers if k != "CB-ACCESS-SIGN"})

        r = requests.get(url, headers=headers, timeout=15)
        print("DEBUG HTTP STATUS:", r.status_code)
        print("DEBUG HTTP BODY:", r.text)

        if r.status_code == 401:
            raise RuntimeError("❌ Coinbase API Unauthorized (401). Check API key and permissions.")
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch wallets/accounts: {r.status_code} {r.text}")

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
    print("=== Fetching accounts ===")
    try:
        accounts = client.fetch_accounts()
        print(accounts)
    except Exception as e:
        print(e)

    print("=== Fetching all wallets ===")
    try:
        wallets = client.fetch_all_wallets()
        print(wallets)
    except Exception as e:
        print(e)
