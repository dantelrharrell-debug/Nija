class CoinbaseClient:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def get_spot_price(self, currency_pair="BTC-USD"):
        # Replace with actual API call if keys are valid
        return {"amount": 30000.0}
