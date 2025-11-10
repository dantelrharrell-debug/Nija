import sys
import os
from nija_client import CoinbaseClient

def main():
    # Initialize Coinbase client (advanced = service-key/CDP)
    client = CoinbaseClient(advanced=True, debug=True)
    
    # Fetch advanced accounts
    accounts = client.fetch_advanced_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
