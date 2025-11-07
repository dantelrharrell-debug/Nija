import requests
import json
import os

BASE_URL = os.getenv("NIJA_BASE_URL", "http://localhost:10000")

def test_buy():
    payload = {
        "product_id": "BTC-USD",
        "usd_quote": 10.0,
        "dry_run": True  # Dry-run to avoid real trades
    }
    r = requests.post(f"{BASE_URL}/buy", json=payload)
    print("BUY Response:", json.dumps(r.json(), indent=2))

def test_sell():
    payload = {
        "product_id": "BTC-USD",
        "usd_quote": 5.0,
        "dry_run": True  # Dry-run to avoid real trades
    }
    r = requests.post(f"{BASE_URL}/sell", json=payload)
    print("SELL Response:", json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    print("Testing NIJA trading bot endpoints...")
    test_buy()
    test_sell()
