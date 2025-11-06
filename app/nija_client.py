# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import jwt  # PyJWT

# ---------- DEBUG ENV ----------
def mask(v, keep=4):
    if v is None:
        return None
    s = str(v)
    if len(s) <= keep * 2:
        return s[:keep] + "..." + s[-keep:]
    return s[:keep] + "..." + s[-keep:]

keys = sorted([k for k in os.environ.keys() if k.upper().startswith("COINBASE") or k.upper().startswith("CDP")])
print("DBG KEYS:", keys)
print("DBG - COINBASE_API_KEY:", mask(os.getenv("COINBASE_API_KEY")))
print("DBG - COINBASE_API_SECRET:", mask(os.getenv("COINBASE_API_SECRET")))
print("DBG - COINBASE_PASSPHRASE:", mask(os.getenv("COINBASE_PASSPHRASE")))
print("DBG - CDP_API_KEY_ID:", mask(os.getenv("CDP_API_KEY_ID")))
print("DBG - CDP_API_KEY_SECRET:", mask(os.getenv("CDP_API_KEY_SECRET")))

# Ensure at least one auth method is available
if not (all([os.getenv("COINBASE_API_KEY"), os.getenv("COINBASE_API_SECRET"), os.getenv("COINBASE_PASSPHRASE")]) or
        all([os.getenv("CDP_API_KEY_ID"), os.getenv("CDP_API_KEY_SECRET")])):
    raise SystemExit("❌ Missing credentials for both HMAC and CDP JWT")
# ---------- end debug ----------

class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials (Exchange API)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        # CDP JWT credentials
        self.cdp_key_id = os.getenv("CDP_API_KEY_ID")
        self.cdp_key_secret = os.getenv("CDP_API_KEY_SECRET")
        self.cdp_base_url = os.getenv("CDP_API_BASE", "https://api.cdp.coinbase.com")

        # choose auth method
        if all([self.api_key, self.api_secret, self.passphrase]):
            self.auth_method = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient")
        elif all([self.cdp_key_id, self.cdp_key_secret]):
            self.auth_method = "CDP_JWT"
            print("✅ Using CDP JWT authentication for CoinbaseClient")
        else:
            raise SystemExit("❌ Missing credentials for both HMAC and CDP JWT")

    # ===== HMAC header builder =====
    def _get_hmac_headers(self, method, path, body=""):
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

    # ===== CDP JWT header builder =====
    def _get_cdp_jwt_headers(self, method, path):
        ts = int(time.time())
        payload = {
            "iat": ts,
            "exp": ts + 120,
            "sub": self.cdp_key_id,
            "path": path,
            "method": method
        }
        token = jwt.encode(payload, self.cdp_key_secret, algorithm="ES256")  # adjust algorithm per key type
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        return headers

    # ===== Fetch accounts via HMAC (debug) =====
    def fetch_accounts(self):
        path = "/accounts"
        method = "GET"
        body = ""
        url = self.base_url + path

        headers = self._get_hmac_headers(method, path, body)

        print("DEBUG SIGNING -> ts:", headers.get("CB-ACCESS-TIMESTAMP"), "method:", method, "path:", path)
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

    # ===== Fetch all wallets via CDP JWT =====
    def fetch_all_wallets(self, limit=50):
        path = "/platform/v1/wallets"
        method = "GET"
        url = self.cdp_base_url + path + f"?limit={limit}"

        headers = self._get_cdp_jwt_headers(method, path)

        print("DEBUG CDP FETCH -> method:", method, "path:", path, "url:", url)
        print("DEBUG HEADERS (masked):", {"Authorization": f"Bearer {self.cdp_key_id[:4]}...{self.cdp_key_id[-4:]}"})

        r = requests.get(url, headers=headers, timeout=15)
        print("DEBUG HTTP STATUS:", r.status_code)
        print("DEBUG HTTP BODY:", r.text)

        if r.status_code == 401:
            raise RuntimeError("❌ CDP Wallets API Unauthorized (401). Check CDP API key and permissions.")
        if r.status_code != 200:
            raise RuntimeError(f"❌ Failed to fetch wallets/accounts: {r.status_code} {r.text}")

        return r.json().get("data", [])

    # ===== Get first funded account from HMAC accounts list =====
    def get_funded_account(self, min_balance=1.0):
        accounts = self.fetch_accounts()
        account_list = accounts.get("data", accounts) if isinstance(accounts, dict) else accounts
        for acct in account_list:
            bal_info = acct.get("balance", acct)
            balance = float(bal_info.get("amount", bal_info if isinstance(bal_info, (int, float)) else 0))
            if balance >= min_balance:
                return acct
        raise RuntimeError("❌ No funded account found")

    # ===== Get first funded wallet from CDP wallets list =====
    def get_funded_wallet(self, min_balance=1.0):
        wallets = self.fetch_all_wallets()
        for w in wallets:
            bal = None
            if "balance" in w:
                try:
                    bal = float(w["balance"].get("amount", "0"))
                except:
                    bal = None
            if bal is not None and bal >= min_balance:
                return w
        raise RuntimeError("❌ No funded wallet found")

# ===== Quick test / live usage =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
    print("=== Using method:", client.auth_method)

    if client.auth_method == "HMAC":
        print("Fetching trading accounts (HMAC):")
        try:
            acct = client.get_funded_account(min_balance=1)
            print("Funded account:", acct)
        except Exception as e:
            print("Error:", e)
    if client.auth_method == "CDP_JWT":
        print("Fetching wallet accounts (CDP):")
        try:
            wallet = client.get_funded_wallet(min_balance=1)
            print("Funded wallet:", wallet)
        except Exception as e:
            print("Error:", e)
