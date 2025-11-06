# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import jwt  # PyJWT needed

# ---------- Hardcoded credentials for testing (replace with env vars in production) ----------
COINBASE_API_KEY = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
COINBASE_API_SECRET = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----"""
COINBASE_PASSPHRASE = "14f3af21-7544-412c-8409-98dc92cd2eec"
# -----------------------------------------------------------------------------------------

def mask(v, keep=4):
    if v is None:
        return None
    s = str(v)
    if len(s) <= keep * 2:
        return s[:keep] + "..." + s[-keep:]
    return s[:keep] + "..." + s[-keep:]

print("DBG - COINBASE_API_KEY:", mask(COINBASE_API_KEY))
print("DBG - COINBASE_API_SECRET:", mask(COINBASE_API_SECRET))
print("DBG - COINBASE_PASSPHRASE:", mask(COINBASE_PASSPHRASE))

class CoinbaseClientWrapper:
    def __init__(self):
        # HMAC credentials
        self.api_key = COINBASE_API_KEY
        self.api_secret = COINBASE_API_SECRET
        self.passphrase = COINBASE_PASSPHRASE
        self.base_url = "https://api.pro.coinbase.com"

        self.auth_method = "HMAC"
        print("✅ Using HMAC authentication for CoinbaseClient")

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

    # ===== Fetch accounts via HMAC (debug) =====
    def fetch_accounts(self):
        path = "/accounts"
        method = "GET"
        body = ""
        url = self.base_url + path

        headers = self._get_hmac_headers(method, path, body)

        print("DEBUG SIGNING -> ts:", headers.get("CB-ACCESS-TIMESTAMP"), "method:", method, "path:", path, "body_len:", len(body))
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

# ===== Quick test / live usage =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
    print("=== Using method:", client.auth_method)

    print("Fetching trading accounts (HMAC):")
    try:
        acct = client.get_funded_account(min_balance=1)
        print("Funded account:", acct)
    except Exception as e:
        print("Error:", e)
