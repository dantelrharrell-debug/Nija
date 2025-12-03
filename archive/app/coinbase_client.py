import os
from importlib import import_module

class NijaCoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE_URL")

        if not self.api_key or not self.api_secret:
            raise RuntimeError("Missing Coinbase API environment variables")

        # Load REST modules dynamically
        self.accounts_mod = import_module("coinbase.rest.accounts")
        self.products_mod = import_module("coinbase.rest.products")
        self.market_mod = import_module("coinbase.rest.market_data")

    # ------------------------
    # ACCOUNT LISTING FUNCTION
    # ------------------------
    def list_accounts(self):
        """
        Calls get_accounts() whether it exists as:
        - a top-level function, or
        - a method on a class inside coinbase.rest.accounts
        """

        acct_mod = self.accounts_mod

        # A) Does module have top-level get_accounts?
        if hasattr(acct_mod, "get_accounts"):
            try:
                return acct_mod.get_accounts(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    api_passphrase=self.api_passphrase
                )
            except TypeError:
                # try without params if SDK doesn't accept them
                return acct_mod.get_accounts()

        # B) No top-level function → search for class
        for name in dir(acct_mod):
            obj = getattr(acct_mod, name)
            if isinstance(obj, type) and hasattr(obj, "get_accounts"):
                try:
                    client = obj(
                        api_key=self.api_key,
                        api_secret=self.api_secret,
                        api_passphrase=self.api_passphrase
                    )
                except:
                    client = obj()
                return client.get_accounts()

        raise RuntimeError("Could not find any get_accounts implementation")
