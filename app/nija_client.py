import os
import stat
import time
import jwt
import requests

class CoinbaseClientWrapper:
    def __init__(self):
        # Try HMAC auth first
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.client_type = None

        if api_key and api_secret and passphrase:
            # Use HMAC
            self.api_key = api_key
            self.api_secret = api_secret
            self.passphrase = passphrase
            self.base_url = base_url
            self.client_type = "HMAC"
            print("✅ Using HMAC authentication for CoinbaseClient")

        elif pem_content:
            # Write PEM to file
            pem_path = "coinbase.pem"
            with open(pem_path, "w") as f:
                f.write(pem_content)
            os.chmod(pem_path, 0o600)
            self.pem_path = pem_path
            self.iss = os.getenv("COINBASE_ISS")
            self.client_type = "JWT"
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
        signature = base64.b64encode(
            hmac.new(base64.b64decode(self.api_secret), message.encode(), hashlib.sha256).digest()
        ).decode()

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
