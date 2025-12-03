#!/usr/bin/env python3
import sys
import os
from nija_hmac_client import CoinbaseClient  # HMAC client
from nija_trading_loop import run_trading_loop  # your trading loop

# --- HMAC Account Verification ---
print("Verifying HMAC keys and fetching accounts...")

try:
    client = CoinbaseClient()
    status, accounts = client.request(method="GET", path="/v2/accounts")
    if status != 200:
        raise Exception(f"Failed to fetch accounts: {accounts}")

    print("✅ Accounts fetched successfully:")
    for acct in accounts.get("data", []):
        print(f" - {acct['name']} ({acct['currency']}): {acct['balance']['amount']}")

except Exception as e:
    print(f"❌ HMAC Account verification failed: {e}")
    print("Aborting bot startup. Check API key permissions and HMAC setup.")
    sys.exit(1)  # Stop the bot if verification fails

print("HMAC verification complete. Starting live bot...")
# =====================================

# --- Start Trading Loop ---
def main():
    live_trading = os.getenv("LIVE_TRADING") == "1"
    if not live_trading:
        print("⚠️ LIVE_TRADING not enabled, exiting.")
        return

    print("⚡ Starting Nija live trading loop...")
    run_trading_loop(client)  # uses the verified HMAC client

if __name__ == "__main__":
    main()
