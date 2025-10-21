class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key
        self.api_secret = api_secret

    def get_spot_price(self, currency_pair="BTC-USD"):
        return {"amount": 30000.0}  # placeholder for live API
