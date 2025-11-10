# nija_client.py
"""Minimal, self-contained client that always exports CoinbaseClient."""

import os
import time
import threading
import requests
from loguru import logger

class CoinbaseClient:
    """Minimal CoinbaseClient for import testing and basic fetch stubs."""

    def __init__(self, base=None, refresh_interval=240):
        self.base = (base or os.getenv("COINBASE_BASE") or "https://api.cdp.coinbase.com").rstrip("/")
        self.jwt = None
        self.refresh_interval = int(refresh_interval)
        self._start_jwt_refresh()
        logger.info("CoinbaseClient initialized (minimal). base=%s", self.base)

    def _start_jwt_refresh(self):
        # no-op refresh thread kept minimal so module can import safely
        def _loop():
            while True:
                time.sleep(self.refresh_interval)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def fetch_accounts(self):
        """Stub: attempt real request if env and network allow, else return []"""
        try:
            url = self.base + "/ping"  # deliberately benign; many Coinbase hosts will 404
            r = requests.get(url, timeout=5)
            logger.debug("fetch_accounts test ping: %s %s", r.status_code, r.text[:200])
        except Exception as e:
            logger.debug("fetch_accounts ping exception (expected in many envs): %s", e)
        return []

    def get_balances(self):
        return {}
