import sys
import os

# Optional: include app folder in path if you have helpers there
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

from nija_client import CoinbaseClient  # Import the robust client from root

def main():
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_advanced_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
