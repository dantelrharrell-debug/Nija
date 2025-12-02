import os
from coinbase_advanced.client import Client

def main():
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # optional, if used

    if not api_key or not api_secret:
        raise RuntimeError("Coinbase API credentials are missing!")

    client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)

    # Quick check to verify connection
    accounts = client.get_accounts()
    print("Connected! Coinbase accounts:")
    for acc in accounts:
        print(f"- {acc['currency']}: {acc['balance']}")

    # TODO: insert your full live trading logic here
    if os.environ.get("LIVE_TRADING") == "1":
        print("LIVE TRADING ENABLED - bot is now trading!")

if __name__ == "__main__":
    main()
