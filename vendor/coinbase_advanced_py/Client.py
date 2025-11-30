# coinbase_advanced_py/client.py
"""
Minimal fallback Client implementation that mirrors the real client's surface,
so tests and non-production runs can import Client. If the official package
is installed, the real Client will be used instead (see shim below).
"""
import logging
logger = logging.getLogger(__name__)

class Client:
    def __init__(self, api_key=None, api_secret=None, api_sub=None, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_sub = api_sub
        logger.info("Fallback coinbase_advanced_py.Client initialized (no real API calls).")

    def ping(self):
        """
        Lightweight test method used by nija_client.test_coinbase_connection().
        Returns True if credentials look present, False otherwise.
        """
        if self.api_key and self.api_secret:
            return True
        return False

    # Add any other minimal methods your app uses (placeholders) to avoid AttributeError.
