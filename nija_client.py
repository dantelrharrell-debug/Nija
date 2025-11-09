# nija_client.py

import os
import time
import json
import requests
import jwt
from loguru import logger
from typing import Dict, Any

# === CoinbaseClient for Advanced / HMAC / JWT authentication ===
class CoinbaseClient:
    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        passphrase: str = None,
        org_id: str = None,
        base: str = None,
        private_key_path: str = None,
    ):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_PASSPHRASE")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.private_key_path = private_key_path or os.getenv("COINBASE_PRIVATE_KEY_PATH")

        # JWT setup if private key exists
        self.jwt_token = None
        if self.private_key_path and os.path.exists(self.private_key_path):
            try:
                with open(self.private_key_path, "r") as f:
                    self.private_key = f.read()
                self.jwt_token = self._generate_jwt()
                logger.success("JWT generated from private key")
            except Exception as e:
                logger.error(f"JWT generation failed: {e}")
                self.jwt_token = None
        else:
            self.private_key = None

        logger.info("CoinbaseClient initialized")
        logger.info(f"Advanced mode: {'Yes' if self.jwt_token or self.api_key else 'No'}")

    # --- JWT generation ---
    def _generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "iss": os.getenv("COINBASE_ISS", self.org_id),
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    # --- Base headers for requests ---
    def _headers(self):
        if self.jwt_token:
            return {"Authorization": f"Bearer {self.jwt_token}"}
        # Fallback HMAC (CB-ACCESS-SIGN style)
        ts = str(int(time.time()))
        sig = self._hmac_sign(ts, "GET", "/v2/accounts", "")
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def _hmac_sign(self, timestamp: str, method: str, path: str, body: str):
        import hmac, hashlib, base64
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode()

    # --- Fetch raw accounts list ---
    def fetch_accounts(self):
        try:
            url = f"{self.base}/v2/accounts"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return {"data": []}

    # --- Compute account balances dict ---
    def get_account_balances(self) -> Dict[str, Any]:
        try:
            accounts = self.fetch_accounts()
            balances = {}
            for acc in accounts.get("data", []):
                balances[acc["currency"]] = float(acc["balance"]["amount"])
            return balances
        except Exception as e:
            logger.error(f"Error in get_account_balances: {e}")
            return {}

# === Backwards-compatibility aliases ===
def _alias_if_missing():
    try:
        if not hasattr(CoinbaseClient, "get_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.get_accounts = CoinbaseClient.fetch_accounts

        if not hasattr(CoinbaseClient, "get_balances"):
            if hasattr(CoinbaseClient, "get_account_balances"):
                CoinbaseClient.get_balances = CoinbaseClient.get_account_balances
            elif hasattr(CoinbaseClient, "get_accounts"):
                def _get_balances(self):
                    return self.get_accounts()
                CoinbaseClient.get_balances = _get_balances

        if not hasattr(CoinbaseClient, "list_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.list_accounts = CoinbaseClient.fetch_accounts
    except Exception:
        pass

_alias_if_missing()
