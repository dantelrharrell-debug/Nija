import os
import time
import json
import requests
from nija_client import CoinbaseClient, calculate_position_size

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

    def calculate_trade_size(self):
        return calculate_position_size(self.balance, risk_factor=self.risk_factor)

    def place_order(self, product_id, side, order_type="market", size=None):
        if not size:
            size = self.calculate_trade_size()
        endpoint = "/v2/orders"
        body = {
            "product_id": product_id,
            "side": side.upper(),
            "type": order_type,
            "size": str(size)
        }
        body_json = json.dumps(body)
        headers = {
            "Authorization": f"Bearer {self.client._generate_jwt('POST', endpoint, body_json)}",
            "Content-Type": "application/json"
        }
        response = requests.post(self.client.base_url + endpoint, headers=headers, data=body_json)
        if response.ok:
            print(f"✅ Order placed: {side} {size} {product_id}")
            return response.json()
        else:
            print(f"❌ Order failed: {response.status_code} {response.text}")
            return None

    def trade_example(self):
        """Example function to demonstrate trading"""
        product_id = "BTC-USD"
        side = "buy"
        trade_size = self.calculate_trade_size()
        print(f"💰 Attempting to {side} {trade_size} {product_id}")
        self.place_order(product_id, side, size=trade_size)

if __name__ == "__main__":
    trader = NijaTrader(risk_factor=5)
    # Example: trade once, replace with alert-based triggers for real trading
    trader.trade_example()
