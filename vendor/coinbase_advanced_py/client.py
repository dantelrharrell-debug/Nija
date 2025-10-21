# client.py — minimal CoinbaseClient stub (simulation-ready)
class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key
        self.api_secret = api_secret
        if not api_key or not api_secret:
            # running without keys -> simulation mode
            print("⚠️ No API keys provided. Running in simulation mode.")

    def get_spot_price(self, currency_pair="BTC-USD"):
        """
        Simulation: returns dummy price.
        Replace method body with real API calls if you install the real lib.
        """
        return {"amount": 30000.0}
