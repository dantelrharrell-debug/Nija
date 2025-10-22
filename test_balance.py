cat > test_balance.py <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

from nija_client import client

# --- Optional: test Coinbase balance ---
def fetch_account_balance(client):
    if not client:
        print("⚠️ No client attached (simulation mode).")
        return None
    try:
        accounts = client.get_accounts()
        total_usd = 0
        for acc in accounts:
            if acc.get("available_balance") and acc["available_balance"]["currency"] == "USD":
                total_usd += float(acc["available_balance"]["value"])
        print("✅ Live Coinbase connection confirmed.")
        print(f"💰 Available USD balance: ${total_usd:.2f}")
        return total_usd
    except Exception as e:
        print(f"⚠️ Failed to fetch balance: {e}")
        return None

# Run test
if __name__ == "__main__":
    fetch_account_balance(client)
PY
