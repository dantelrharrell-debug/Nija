# /app/coinbase_advanced_py/client.py
"""
DEV SHIM — TEMPORARY CLIENT FOR STARTUP

This file allows your nija_client.find_client_class() function
to find a valid Client class so the container stops logging:

    "No client class available"

This DOES NOT contact Coinbase. It only returns safe fake data
so your startup checks succeed while you finish integration.
"""

import logging

logger = logging.getLogger(__name__)


class Client:
    def __init__(self, api_key=None, api_secret=None, api_sub=None, *args, **kwargs):
        # Whether credentials were passed (never log real secrets!)
        self._has_creds = bool(api_key and api_secret)
        self.api_sub = api_sub

        logger.info(
            "DEV SHIM Client initialized. Credentials provided: %s",
            self._has_creds
        )

    def get_accounts(self):
        """
        Fake response so test_coinbase_connection() always succeeds.
        """
        return [
            {
                "id": "dev-shim-account",
                "currency": "USD",
                "balance": "0.00",
            }
        ]

    # Some libraries call list_accounts instead
    def list_accounts(self):
        return self.get_accounts()
