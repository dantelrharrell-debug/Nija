# nija_client.py
import os
from loguru import logger

# Official SDK exposes REST client via coinbase.rest.RESTClient per docs
# (Coinbase docs show usage: from coinbase.rest import RESTClient).
try:
    from coinbase.rest import RESTClient
except Exception as e:
    logger.exception("coinbase.rest import failed — SDK may not be installed or import path changed.")
    raise

class CoinbaseClient:
    """
    Simple wrapper for Coinbase Advanced REST client.
    Supports either PEM/JWT org-style auth or API key/secret if you prefer.
    Check Coinbase docs for the auth style you will use.
    """
    def __init__(self):
        # Expect either PEM-style JWT credentials, or API key + secret
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")  # multi-line PEM
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional

        # Choose auth strategy
        if self.pem and self.org_id:
            # PEM-based (recommended for Advanced API / orgs)
            # RESTClient can accept api_key as "organizations/{org_id}/apiKeys/{key_id}" and pem as secret for JWT,
            # but many setups use RESTClient(pem=..., org_id=...) — check SDK docs for exact constructor options.
            logger.info("Initializing Coinbase RESTClient using PEM/ORG auth")
            # The exact RESTClient constructor depends on SDK version; below is a common pattern:
            self.client = RESTClient(pem=self.pem, org_id=self.org_id)
        elif self.api_key and self.api_secret:
            logger.info("Initializing Coinbase RESTClient using API key/secret")
            # API-key constructor commonly like RESTClient(api_key=..., api_secret=..., api_passphrase=...)
            self.client = RESTClient(api_key=self.api_key, api_secret=self.api_secret, api_passphrase=self.api_passphrase)
        else:
            raise ValueError("Missing Coinbase credentials. Set COINBASE_PEM_CONTENT + COINBASE_ORG_ID OR COINBASE_API_KEY + COINBASE_API_SECRET")

    def list_accounts(self):
        """
        Example wrapper that calls the SDK to list accounts.
        SDK method names vary; commonly `get_accounts()` or `accounts()` — check the SDK version docs.
        We'll attempt a few common method names gracefully.
        """
        try:
            # Try common method names used by SDKs
            if hasattr(self.client, "get_accounts"):
                return self.client.get_accounts()
            if hasattr(self.client, "accounts"):
                return self.client.accounts()
            # fallback: attempt HTTP call via RESTClient
            return self.client.request("GET", "/accounts")
        except Exception as e:
            logger.exception("Error fetching accounts from Coinbase")
            raise
