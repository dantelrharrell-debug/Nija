# nija_client.py
import os
from loguru import logger

try:
    # Official SDK import that worked for you
    from coinbase.rest import RESTClient
except Exception as e:
    logger.exception("coinbase.rest import failed.")
    raise

class CoinbaseClient:
    def __init__(self):
        # Prefer PEM/ORG method if provided (Advanced organizations)
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE") or None

        if self.pem and self.org_id:
            logger.info("Initializing RESTClient using PEM/ORG auth")
            # SDK constructors vary — this is a common pattern. If your SDK uses different kwargs, adjust here.
            self.client = RESTClient(pem=self.pem, org_id=self.org_id)
        elif self.api_key and self.api_secret:
            logger.info("Initializing RESTClient using API key/secret")
            self.client = RESTClient(api_key=self.api_key, api_secret=self.api_secret, api_passphrase=self.api_passphrase)
        else:
            raise ValueError("Missing Coinbase credentials. Set COINBASE_PEM_CONTENT+COINBASE_ORG_ID OR COINBASE_API_KEY+COINBASE_API_SECRET")

    def _call_accounts(self):
        """
        Call the most likely method names for the installed SDK.
        Return a list-like object or raise.
        """
        # Try common method names safely
        if hasattr(self.client, "get_accounts"):
            return self.client.get_accounts()
        if hasattr(self.client, "accounts"):
            # some SDK use client.accounts.list() or client.accounts()
            acct_attr = self.client.accounts
            if callable(acct_attr):
                return acct_attr()
            # try .list()
            if hasattr(acct_attr, "list"):
                return acct_attr.list()
        # fallback to raw REST request if SDK supports .request
        if hasattr(self.client, "request"):
            return self.client.request("GET", "/accounts")
        raise RuntimeError("No known accounts method on RESTClient")

    def list_accounts(self):
        return self._call_accounts()
