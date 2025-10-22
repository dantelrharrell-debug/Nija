import sys, os

# Ensure vendor path is included
sys.path.insert(0, os.path.join(os.getcwd(), "vendor"))

# Import trading loop flag
try:
    from debug_client_full import running  # your bot's trading loop flag
except Exception:
    running = False

# Import Coinbase client
try:
    from coinbase_advanced_py.client import CoinbaseClient
except Exception:
    print("❌ Could not import CoinbaseClient. Check your vendor folder.")
    sys.exit(1)

# -------------------------
# CONFIG - Replace with your real keys
# -------------------------
API_KEY = "YOUR_API_KEY_HERE"
API_SECRET = "YOUR_API_SECRET_HERE"

# -------------------------
# Connect to Coinbase
# -------------------------
try:
    client = CoinbaseClient(API_KEY, API_SECRET)
    accounts = client.get_accounts()
    coinbase_status = "✅ Connected" if accounts else "⚠️ No accounts returned"
except Exception as e:
    coinbase_status = f"❌ Error: {e}"
    accounts = []

# -------------------------
# Check open positions
# -------------------------
positions = []
if accounts:
    try:
        open_orders = client.get_open_orders()
        for order in open_orders:
            # Adjust keys depending on your API response
            symbol = order.get("product_id", "N/A")
            side = order.get("side", "N/A")
            size = order.get("size", "N/A")
            positions.append(f"{symbol} | {side} | {size}")
    except Exception as e:
        positions.append(f"⚠️ Error fetching positions: {e}")

# -------------------------
# Print snapshot
# -------------------------
print("\n===== NIJA BOT LIVE SNAPSHOT =====")
print(f"Trading Loop: {'✅ Live' if running else '❌ Stopped'}")
print(f"Coinbase API: {coinbase_status}")
print(f"Number of Accounts: {len(accounts)}")
print(f"Open Orders/Positions ({len(positions)}):")
if positions:
    for p in positions:
        print(f"  - {p}")
else:
    print("  None")
print("=================================\n")
