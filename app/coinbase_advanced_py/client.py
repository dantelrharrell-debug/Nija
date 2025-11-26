# /app/coinbase_advanced_py/client.py
"""
Development shim so nija_client.find_client_class() can find a Client.
This is a harmless stub — it DOES NOT contact Coinbase.
Replace with real client wrapper when ready.
"""
import os
import logging

logger = logging.getLogger(__name__)

class Client:
    def __init__(self, api_key=None, api_secret=None, api_sub=None, *args, **kwargs):
        # store keys for debug only; don't log secrets
        self._has_creds = bool(api_key and api_secret)
        self.api_sub = api_sub
        logger.info("coinbase_advanced_py.client.Client initialized (stub) - creds provided: %s", self._has_creds)

    # Provide a harmless read-only method the startup test can call
    def get_accounts(self):
        """
        Return a fake accounts list for the connection test.
        Keep this method lightweight and deterministic.
        """
        return [{"id": "stub-acc-1", "currency": "USD", "balance": "0.00"}]

    # optional alias methods some tests try
    def list_accounts(self):
        return self.get_accounts()
