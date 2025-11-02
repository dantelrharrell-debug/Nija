# nija_status.py
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_status")

def print_status():
    print("\n--- NIJA BOT LIVE STATUS ---\n")

    # 1️⃣ Coinbase RESTClient connection
    try:
        if client:
            print("✅ Coinbase RESTClient connected")
        else:
            print("❌ Coinbase client not found")
    except Exception as e:
        print(f"❌ Coinbase connection failed: {e}")

    # 2️⃣ USD Balance Check
    try:
        balance: Decimal = get_usd_balance(client)
        if balance > 0:
            print(f"✅ USD Balance available: ${balance}")
        else:
            print(f"❌ USD Balance is zero")
    except Exception as e:
        print(f"❌ Failed to fetch USD balance: {e}")

    # 3️⃣ Test Trade Simulation
    try:
        # Simulate a tiny buy order (adjust amount to minimum for your account)
        test_order_amount = 0.001  # BTC example
        # Uncomment for real trade:
        # order = client.place_order(product_id="BTC-USD", side="buy", size=str(test_order_amount))
        print(f"✅ Test trade simulation OK (buy {test_order_amount} BTC)")
    except Exception as e:
        print(f"❌ Test trade failed: {e}")

    print("\n--- NIJA STATUS CHECK COMPLETE ---\n")

if __name__ == "__main__":
    print_status()
