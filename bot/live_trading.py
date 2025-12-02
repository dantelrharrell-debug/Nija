import os
from coinbase_advanced_py.client import Client

def run_live_trading():
    # Pull keys from environment
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")  # optional

    client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
    
    accounts = client.get_accounts()
    print("Accounts:", accounts)

if __name__ == "__main__":
    run_live_trading()
