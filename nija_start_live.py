# ===== HMAC Account Verification =====
from nija_hmac_client import CoinbaseClient

print("Verifying HMAC keys and fetching accounts...")

try:
    client = CoinbaseClient()
    status, accounts = client.get_accounts()

    if status != 200:
        raise Exception(f"Failed to fetch accounts: {accounts}")

    print("✅ Accounts fetched successfully:")
    for acct in accounts.get("data", []):
        print(f" - {acct['name']} ({acct['currency']}): {acct['balance']['amount']}")

except Exception as e:
    print(f"❌ HMAC Account verification failed: {e}")
    print("Aborting bot startup. Check API key permissions and HMAC setup.")
    import sys
    sys.exit(1)  # Stop the bot if verification fails

print("HMAC verification complete. Starting live bot...")
# =====================================

import os
from nija_client import CoinbaseClient
from nija_trading_loop import run_trading_loop

def main():
    live_trading = os.getenv("LIVE_TRADING") == "1"
    if not live_trading:
        print("⚠️ LIVE_TRADING not enabled, exiting.")
        return

    client = CoinbaseClient()
    accounts = client.list_accounts()
    if not accounts:
        print("❌ No accounts found. Cannot trade live.")
        return

    print("✅ Connected accounts:", accounts)
    print("⚡ Starting Nija live trading loop...")
    run_trading_loop(client)  # your main trading function

if __name__ == "__main__":
    main()
