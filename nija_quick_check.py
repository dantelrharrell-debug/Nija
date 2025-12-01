import sys, os

# Ensure vendor path is included
sys.path.insert(0, os.path.join(os.getcwd(), "vendor"))

# Import your trading loop flag and Coinbase client
try:
    from debug_client_full import running  # flag your bot uses
except Exception:
    running = False

try:
    
except Exception:
    print("❌ Could not import CoinbaseClient. Check your vendor folder.")
    sys.exit(1)

# -------------------------
# CONFIG - Replace with your real keys
# -------------------------
API_KEY = "YOUR_API_KEY_HERE"
API_SECRET = "YOUR_API_SECRET_HERE"

# -------------------------
# Check Coinbase connection
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
try:
    open_orders = client.get_open_orders() if accounts else []
    positions_count = len(open_orders)
except Exception:
    positions_count = 0

# -------------------------
# Print summary
# -------------------------
print("\n===== NIJA BOT QUICK CHECK =====")
print(f"Trading Loop: {'✅ Live' if running else '❌ Stopped'}")
print(f"Coinbase API: {coinbase_status}")
print(f"Number of Accounts: {len(accounts)}")
print(f"Open Orders/Positions: {positions_count}")
print("================================\n")
