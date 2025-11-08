# --- BEGIN get_accounts patch ---
from nija_client import CoinbaseClient as OriginalCoinbaseClient

# Only patch once
if not hasattr(OriginalCoinbaseClient, "get_accounts"):
    def get_accounts(self, *args, **kwargs):
        # Redirect to fetch_accounts
        return self.fetch_accounts(*args, **kwargs)
    
    setattr(OriginalCoinbaseClient, "get_accounts", get_accounts)
# --- END get_accounts patch ---
