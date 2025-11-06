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
