# nija_coinbase_advanced.py
import os
import time
import json
import logging
import requests
from loguru import logger

# Optional PyJWT
try:
    import jwt as pyjwt
    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False

logger = logger.bind(name="nija_coinbase_advanced")

# Env vars
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", "")
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH", "")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
AUTO_JWT_LIFETIME = 600  # 10 minutes

class CoinbaseAdvancedClient:
    def __init__(self):
        self.jwt = None
        self.base = COINBASE_API_BASE
        self._setup_jwt()

    def _setup_jwt(self):
        if self.jwt:
            return

        # 1) Use raw PEM content
        pem_bytes = None
        if COINBASE_PEM_CONTENT:
            pem_bytes = COINBASE_PEM_CONTENT.encode()
        elif COINBASE_PRIVATE_KEY_PATH and os.path.exists(COINBASE_PRIVATE_KEY_PATH):
            with open(COINBASE_PRIVATE_KEY_PATH, "rb") as f:
                pem_bytes = f.read()

        if pem_bytes and COINBASE_ORG_ID and PYJWT_AVAILABLE:
            now = int(time.time())
            payload = {
                "iss": COINBASE_ORG_ID,
                "sub": COINBASE_ORG_ID,
                "iat": now,
                "exp": now + AUTO_JWT_LIFETIME,
                "aud": "coinbase",
            }
            try:
                token = pyjwt.encode(payload, pem_bytes, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                logger.info("Generated ephemeral JWT from PEM (valid 10 minutes).")
            except Exception as e:
                logger.error(f"JWT generation failed: {e}")
        else:
            logger.error("Cannot generate JWT: missing PEM, ORG_ID, or PyJWT.")

    def _bearer_headers(self):
        if not self.jwt:
            raise RuntimeError("JWT not initialized")
        return {
            "Authorization": f"Bearer {self.jwt}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nija-advanced-client/1.0",
        }

    def _get(self, path):
        url = self.base.rstrip("/") + "/" + path.lstrip("/")
        try:
            resp = requests.get(url, headers=self._bearer_headers(), timeout=8)
            if resp.status_code != 200:
                logger.warning(f"GET {url} returned {resp.status_code}: {resp.text[:500]}")
                return None
            try:
                return resp.json()
            except Exception:
                logger.warning(f"Failed to parse JSON from {url}")
                return None
        except Exception as e:
            logger.error(f"Request failed {url}: {e}")
            return None

    def fetch_accounts(self):
        endpoints = [
            "/platform/v2/evm/accounts",
            "/platform/v2/accounts",
        ]
        for ep in endpoints:
            data = self._get(ep)
            if data:
                accounts = data.get("accounts") or data.get("data") or []
                logger.info(f"Fetched {len(accounts)} account(s) from {ep}")
                return accounts
        logger.error("No accounts fetched from any endpoint")
        return []

    def get_accounts(self):
        return self.fetch_accounts()

    def get_spot_account_balances(self):
        balances = {}
        accounts = self.fetch_accounts()
        for a in accounts:
            c = a.get("currency") or a.get("currency_code")
            amt = a.get("balance", {}).get("amount") or a.get("available_balance") or 0
            if c:
                balances[c.upper()] = float(amt)
        return balances


# Singleton instance for easy import
client = CoinbaseAdvancedClient()

# Module-level functions for compatibility
def get_accounts():
    return client.get_accounts()

def fetch_accounts():
    return client.fetch_accounts()

def get_spot_account_balances():
    return client.get_spot_account_balances()


# Optional diagnostic run
if __name__ == "__main__":
    accs = fetch_accounts()
    logger.info(f"Diagnostic: found {len(accs)} account(s)")
    balances = get_spot_account_balances()
    logger.info(f"Spot balances: {balances}")
