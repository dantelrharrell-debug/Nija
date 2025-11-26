# /app/coinbase_advanced_py/client.py
"""
DEV SHIM — TEMPORARY CLIENT FOR STARTUP

Safe fake client so startup connection test passes while you finish integration.
This DOES NOT contact Coinbase.
"""

import logging
logger = logging.getLogger(__name__)


class Client:
    def __init__(self, api_key=None, api_secret=None, api_sub=None, *args, **kwargs):
        # Do NOT log secrets — only presence/absence
        self._has_creds = bool(api_key and api_secret)
        self.api_sub = api_sub
        logger.info("DEV SHIM Client initialized. Credentials provided: %s", self._has_creds)

    def get_accounts(self):
        return [{"id": "dev-shim-account", "currency": "USD", "balance": "0.00"}]

    def list_accounts(self):
        return self.get_accounts()
