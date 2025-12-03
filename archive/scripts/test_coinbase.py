# scripts/test_coinbase.py
import os
from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient(
        api_key=os.environ.get("COINBASE_API_KEY"),
        api_secret=os.environ.get("COINBASE_API_SECRET"),
        passphrase=os.environ.get("COINBASE_API_PASSPHRASE"),
        org_id=os.environ.get("COINBASE_ORG_ID"),
        private_key_path=os.environ.get("COINBASE_PRIVATE_KEY_PATH"),
        jwt=os.environ.get("COINBASE_JWT")
    )
    accounts = client.fetch_accounts()
    print("Accounts:", accounts)

if __name__ == "__main__":
    main()
