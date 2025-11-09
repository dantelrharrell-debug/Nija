# === Backwards-compatibility aliases for start_bot.py & common methods ===
def _alias_if_missing():
    try:
        # Alias get_accounts to fetch_accounts if missing
        if not hasattr(CoinbaseClient, "get_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.get_accounts = CoinbaseClient.fetch_accounts

        # Alias get_balances to existing methods or wrap get_accounts
        if not hasattr(CoinbaseClient, "get_balances"):
            if hasattr(CoinbaseClient, "get_account_balances"):
                CoinbaseClient.get_balances = CoinbaseClient.get_account_balances
            elif hasattr(CoinbaseClient, "get_accounts"):
                def _get_balances(self):
                    return self.get_accounts()
                CoinbaseClient.get_balances = _get_balances

        # Alias list_accounts to fetch_accounts if missing
        if not hasattr(CoinbaseClient, "list_accounts") and hasattr(CoinbaseClient, "fetch_accounts"):
            CoinbaseClient.list_accounts = CoinbaseClient.fetch_accounts

    except Exception:
        # Do not crash if aliasing fails
        pass

try:
    _alias_if_missing()
except Exception:
    pass
