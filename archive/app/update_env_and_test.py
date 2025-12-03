# update_env_and_test.py
from pathlib import Path
import os
import json
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

# --- Step 1: Backup and update .env ---
env_path = Path("/app/.env")
if env_path.exists():
    backup_path = env_path.with_suffix(".env.bak")
    backup_path.write_text(env_path.read_text())
    print(f"Backed up .env to {backup_path}")

    # Remove old COINBASE_API_BASE lines and add Retail base
    lines = [line for line in env_path.read_text().splitlines() if not line.startswith("COINBASE_API_BASE=")]
    lines.append("COINBASE_API_BASE=https://api.coinbase.com")
    env_path.write_text("\n".join(lines))
    print(f"Updated COINBASE_API_BASE in .env to Retail API")

# --- Step 2: Load environment variables ---
load_dotenv(str(env_path))

# --- Step 3: HMAC CoinbaseClient ---
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Optional for Retail
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("Coinbase API key/secret are not set in the environment.")

    def _sign(self, method, path):
        ts = str(int(time.time()))
        prehash = ts + method.upper() + path
        sig = base64.b64encode(
            hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return ts, sig

    def get_accounts(self):
        path = "/v2/accounts"
        ts, sig = self._sign("GET", path)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase or "",
            "CB-VERSION": "2025-11-08",
            "Content-Type": "application/json"
        }
        r = requests.get(self.base_url + path, headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text

# --- Step 4: Test ---
client = CoinbaseClient()
status, data = client.get_accounts()
print("Status:", status)
print(json.dumps(data, indent=2) if isinstance(data, dict) else data)
