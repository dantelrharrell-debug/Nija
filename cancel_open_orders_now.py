#!/usr/bin/env python3
"""
Cancel all OPEN orders immediately on Coinbase Advanced Trade.
Requires COINBASE_API_KEY and COINBASE_API_SECRET in the environment.
"""
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from coinbase.rest import RESTClient
except ImportError:
    print("❌ coinbase-advanced-py not installed or import failed.")
    sys.exit(1)


def main() -> int:
    print("\n" + "=" * 80)
    print("🚨 CANCEL OPEN ORDERS NOW")
    print("=" * 80 + "\n")

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        print("❌ Missing COINBASE_API_KEY / COINBASE_API_SECRET")
        return 1

    client = RESTClient(api_key=api_key, api_secret=api_secret)

    try:
        # Fetch OPEN orders (use broad limit to be safe)
        print("📋 Fetching OPEN orders...")
        resp = client.list_orders(order_status="OPEN", limit=200)
        orders = getattr(resp, "orders", [])
        if not orders:
            print("✅ No open orders found.")
            return 0

        print(f"🔎 Found {len(orders)} open order(s)")
        cancelled = 0
        failed = 0

        # Prefer bulk cancel if available; otherwise cancel individually
        order_ids = []
        for o in orders:
            oid = getattr(o, "order_id", None) or getattr(o, "orderId", None)
            if oid:
                order_ids.append(oid)

        bulk_done = False
        try:
            if order_ids and hasattr(client, "cancel_orders"):
                print("🧹 Attempting bulk cancel...")
                client.cancel_orders(order_ids=order_ids)
                cancelled = len(order_ids)
                bulk_done = True
        except Exception as e:
            print(f"⚠️ Bulk cancel not available/failed: {e}")

        if not bulk_done:
            for oid in order_ids:
                try:
                    if hasattr(client, "cancel_order"):
                        client.cancel_order(order_id=oid)
                        cancelled += 1
                        time.sleep(0.2)
                    else:
                        print("❌ cancel_order not supported by client")
                        failed += 1
                except Exception as e:
                    print(f"❌ Failed to cancel {oid}: {e}")
                    failed += 1

        print("\n" + "=" * 80)
        print("CANCEL SUMMARY")
        print("=" * 80)
        print(f"✅ Cancelled: {cancelled}")
        print(f"❌ Failed: {failed}")
        return 0 if failed == 0 else 2

    except Exception as e:
        print(f"❌ Critical error: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
