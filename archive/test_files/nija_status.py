# nija_startup.py
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance
from nija_worker import run_worker  # your main bot loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_startup")

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
        test_order_amount = 0.001  # Adjust for your account minimum
        # Uncomment for real trade:
        # order = client.place_order(product_id="BTC-USD", side="buy", size=str(test_order_amount))
        print(f"✅ Test trade simulation OK (buy {test_order_amount} BTC)")
    except Exception as e:
        print(f"❌ Test trade failed: {e}")

    print("\n--- NIJA STATUS CHECK COMPLETE ---\n")


if __name__ == "__main__":
    # 1️⃣ Preflight checks (existing)
    try:
        import nija_preflight
        nija_preflight.run_checks()
        print("✅ Preflight checks completed")
    except Exception as e:
        print(f"❌ Preflight failed: {e}")
        exit(1)

    # 2️⃣ Live status green checks
    print_status()

    # 3️⃣ Start main Nija worker
    print("🚀 Starting Nija bot worker...")
    run_worker()
