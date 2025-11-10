# nija_client.py

class CoinbaseClient:
    def __init__(self, base=None, jwt=None):
        self.base = base or "https://api.cdp.coinbase.com"
        self.jwt = jwt
        # other init code

    def get_accounts(self):
        # placeholder for actual API call
        return []

    def get_balance(self):
        # placeholder for actual balance fetch
        return 0
