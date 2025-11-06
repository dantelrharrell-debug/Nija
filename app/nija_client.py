# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import jwt  # PyJWT
import json

# ---------- DEBUG ENV (drop at top for 1 deploy only) ----------
def mask(v, keep=4):
    if v is None: return None
    s = str(v)
    if len(s) <= keep*2: return s[:keep] + "..." + s[-keep:]
    return s[:keep] + "..." + s[-keep:]

keys = sorted([k for k in os.environ.keys() if k.upper().startswith("COINBASE")])
print("DBG KEYS:", keys)
print("DBG - COINBASE_API_KEY:", mask(os.getenv("COINBASE_API_KEY")))
print("DBG - COINBASE_API_SECRET (masked):", mask(os.getenv("COINBASE_API_SECRET")))
print("DBG - COINBASE_PASSPHRASE:", mask(os.getenv("COINBASE_PASSPHRASE")))
print("DBG - COINBASE_API_BASE:", mask(os.getenv("COINBASE_API_BASE")))
print("DBG - COINBASE_JWT_KEY:", mask(os.getenv("COINBASE_JWT_KEY")))
print("DBG - COINBASE_JWT_SECRET:", mask(os.getenv("COINBASE_JWT_SECRET")))

# ---------- Coinbase Client Wrapper ----------
class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        # JWT credentials
        self.jwt_key = os.getenv("COINBASE_JWT_KEY")
        self.jwt_secret = os.getenv("COINBASE_JWT_SECRET")

        # Determine auth method
        self.auth_method = None
        if all([self.api_key, self.api_secret, self.passphrase]):
            self.auth_method = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient")
        elif all([self.jwt_key, self.jwt_secret]):
            self.auth_method = "JWT"
            print("⚠️ HMAC missing, using JWT fallback for CoinbaseClient")
        else:
            raise SystemExit("❌ Missing all Coinbase credentials; cannot authenticate")

        # Try fetching funded account on startup
        try:
            funded = self.get_funded_account(min_balance=1)
            print("✅ Funded account found on startup:", funded)
        except Exception as e:
            print(f"❌ Failed to fetch funded account on startup: {e}")

    # ===== Internal: HMAC headers =====
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

    # ===== Internal: JWT headers =====
    def _get_jwt_headers(self):
        ts = int(time.time())
        payload = {
            "iat": ts,
            "exp": ts + 30,
            "sub": self.jwt_key
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        return headers

    # ===== Fetch accounts with debug =====
    def fetch_accounts(self):
        path = "/accounts"
        method = "GET"
        body = ""
        url = self.base_url + path

        try:
            if self.auth_method == "HMAC":
                headers = self._get_hmac_headers(method, path, body)
            else:
                headers = self._get_jwt_headers()

            # Debug info
            print("DEBUG FETCH_ACCOUNTS -> auth_method:", self.auth_method)
            if self.auth_method == "HMAC":
                ts = headers.get("CB-ACCESS-TIMESTAMP")
                print("DEBUG SIGNING -> ts:", ts, "method:", method, "path:", path, "body_len:", len(body))
                print("DEBUG KEY (masked):", (self.api_key[:4] + "..." + self.api_key[-4:]) if self.api_key else None)
                print("DEBUG HEADERS (no secret):", {k: headers[k] for k in headers if k != "CB-ACCESS-SIGN"})
            r = requests.get(url, headers=headers, timeout=15)
            print("DEBUG HTTP STATUS:", r.status_code)
            print("DEBUG HTTP BODY:", r.text)

            if r.status_code == 401 and self.auth_method == "HMAC" and all([self.jwt_key, self.jwt_secret]):
                # Auto fallback to JWT
                print("⚠️ HMAC Unauthorized, falling back to JWT...")
                self.auth_method = "JWT"
                return self.fetch_accounts()  # Retry with JWT

            if r.status_code != 200:
                raise RuntimeError(f"❌ Failed to fetch accounts: {r.status_code} {r.text}")

            return r.json()

        except Exception as e:
            raise RuntimeError(f"❌ Exception during fetch_accounts: {e}")

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
