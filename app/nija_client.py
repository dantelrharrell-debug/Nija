# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    """
    Minimal CoinbaseClient stub to avoid import errors.
    Later, you can expand with JWT auth, account fetching, etc.
    """
    def __init__(self, base=None, jwt=None):
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.jwt = jwt
        logger.info(f"CoinbaseClient initialized with base={self.base} jwt_set={self.jwt is not None}")

    def get_accounts(self):
        """
        Stub method to avoid crashing.
        Replace with actual API call later.
        """
        logger.info("get_accounts() called — returning empty list for now")
        return []

    def get_balance(self):
        """
        Stub method for balance checks.
        """
        accounts = self.get_accounts()
        total = sum(a.get("balance", 0) for a in accounts)
        logger.info(f"Total balance: {total}")
        return total
