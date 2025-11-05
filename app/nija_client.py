import os
import stat
import time
import jwt
import requests
import hmac
import hashlib

# ✅ Write PEM from environment if present
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if pem_content:
    pem_content = pem_content.replace("\\n", "\n")  # converts \n to actual line breaks
    with open("coinbase.pem", "w") as f:
        f.write(pem_content)
    os.chmod("coinbase.pem", 0o600)  # secure permissions

import os
import time
import hmac
import hashlib
import requests
import jwt

class CoinbaseClientWrapper:
    def __init__(self):
        # Check for HMAC credentials first
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")

        if self.api_key and self.api_secret and self.passphrase:
            self.client_type = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient")
        elif self.pem_content:
            self.client_type = "JWT"
            self.pem_path = "coinbase.pem"
            with open(self.pem_path, "w") as f:
                f.write(self.pem_content)
            os.chmod(self.pem_path, 0o600)
            print("✅ Using JWT/PEM authentication for CoinbaseClient")
        else:
            raise SystemExit(
                "❌ Missing credentials: set either COINBASE_API_KEY/SECRET/PASSPHRASE or COINBASE_PEM_CONTENT"
            )

    def fetch_accounts(self):
        if self.client_type == "HMAC":
            return self._fetch_accounts_hmac()
        elif self.client_type == "JWT":
            return self._fetch_accounts_jwt()
        else:
            raise RuntimeError("Unknown client type")

    def _fetch_accounts_hmac(self):
        ts = str(int(time.time()))
        method = "GET"
        path = "/accounts"
        message = ts + method + path

        # ✅ Fixed signing (no base64 decoding)
        signature = hmac.new(
            self.api_secret.encode(),  # raw secret as bytes
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


# ===== Usage =====
if __name__ == "__main__":
    client = CoinbaseClientWrapper()
    accounts = client.fetch_accounts()
    print("✅ Accounts fetched successfully:")
    print(accounts)
