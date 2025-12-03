import json
import requests
from nija_client import CoinbaseClient

class NijaTrader:
    def __init__(self, risk_factor=5):
        self.client = CoinbaseClient()
        self.risk_factor = risk_factor
        self.funded_account = self.client.get_funded_account()
        if not self.funded_account:
            raise RuntimeError("⚠️ No funded accounts found. Fund your Coinbase account.")
        self.currency = self.funded_account.get("currency")
        self.balance = float(self.funded_account.get("balance", {}).get("amount", 0))
        print(f"✅ Trading from account: {self.currency}, balance: {self.balance}")

    def trade_example(self):
        product_id = "BTC-USD"
        size = self.balance * 0.01  # simple 1% example
        print(f"💰 Attempting to buy {size} {product_id}")
        endpoint = "/v2/orders"
        body = {"product_id": product_id, "side": "buy", "type": "market", "size": str(size)}
        body_json = json.dumps(body)
        headers = {
            "Authorization": f"Bearer {self.client._generate_jwt('POST', endpoint, body_json)}",
            "Content-Type": "application/json"
        }
        response = requests.post(self.client.base_url + endpoint, headers=headers, data=body_json)
        if response.ok:
            print(f"✅ Order placed: {response.json()}")
        else:
            print(f"❌ Order failed: {response.status_code} {response.text}")

if __name__ == "__main__":
    trader = NijaTrader()
    trader.trade_example()
