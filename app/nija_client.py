# /app/nija_client.py
"""
Nija Coinbase Advanced client (PEM/JWT only)
- Uses COINBASE_PEM_CONTENT or COINBASE_PRIVATE_KEY_PATH + COINBASE_ISS to generate JWT.
- Fetches accounts and balances.
- Does not use HMAC / legacy endpoints.
"""

import os
import time
from typing import List, Dict
from loguru import logger

try:
    import jwt  # PyJWT
except ImportError:
    logger.error("PyJWT not installed. Install via `pip install PyJWT`")
    raise

import requests

COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
COINBASE_ISS = os.getenv("COINBASE_ISS")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PRIVATE_KEY_PATH = os.getenv("COINBASE_PRIVATE_KEY_PATH")
AUTO_JWT_LIFETIME = 600  # 10 minutes

class NijaCoinbaseClient:
    def __init__(self):
        logger.info("Initializing NijaCoinbaseClient (PEM/JWT only)")
        self.jwt = None
        if COINBASE_PEM_CONTENT and COINBASE_ISS:
            self.jwt = self._generate_jwt(COINBASE_PEM_CONTENT, COINBASE_ISS)
        elif COINBASE_PRIVATE_KEY_PATH and COINBASE_ISS and os.path.exists(COINBASE_PRIVATE_KEY_PATH):
            with open(COINBASE_PRIVATE_KEY_PATH, "r") as f:
                pem = f.read()
            self.jwt = self._generate_jwt(pem, COINBASE_ISS)
        else:
            logger.error("No valid PEM/JWT configuration found. Set COINBASE_PEM_CONTENT + COINBASE_ISS or COINBASE_PRIVATE_KEY_PATH + COINBASE_ISS")
            raise RuntimeError("Cannot initialize NijaCoinbaseClient without PEM/JWT")

        logger.success("JWT successfully generated. Client ready.")

    def _generate_jwt(self, pem: str, iss: str) -> str:
        now = int(time.time())
        payload = {
            "iss": iss,
            "sub": iss,
            "aud": "coinbase",
            "iat": now,
            "exp": now + AUTO_JWT_LIFETIME,
        }
        token = jwt.encode(payload, pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.jwt}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nija-client/1.0",
        }

    def get_accounts(self) -> List[Dict]:
        url = COINBASE_API_BASE + "/platform/v2/evm/accounts"
        try:
            r = requests.get(url, headers=self._headers(), timeout=8)
            if r.status_code != 200:
                logger.error(f"Accounts fetch failed {r.status_code} {r.text[:200]}")
                return []
            data = r.json()
            return data.get("data") or []
        except Exception as e:
            logger.exception(f"Exception fetching accounts: {e}")
            return []

    def get_balances(self) -> Dict[str, float]:
        accounts = self.get_accounts()
        balances = {}
        for a in accounts:
            currency = a.get("currency") or a.get("currency_code")
            balance = (a.get("balance") or {}).get("amount") or a.get("available_balance") or 0
            if currency:
                balances[currency.upper()] = float(balance)
        return balances

    def get_recent_trades(self, limit: int = 5) -> List[Dict]:
        url = COINBASE_API_BASE + f"/platform/v2/evm/trades?limit={limit}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=8)
            if r.status_code != 200:
                logger.error(f"Trades fetch failed {r.status_code} {r.text[:200]}")
                return []
            data = r.json()
            return data.get("data") or []
        except Exception as e:
            logger.exception(f"Exception fetching trades: {e}")
            return []
