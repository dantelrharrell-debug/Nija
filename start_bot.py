import sys
import os

# Add app folder to path (optional helpers)
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_advanced_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
