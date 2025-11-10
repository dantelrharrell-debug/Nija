from nija_client import CoinbaseClient  # import from root shim

def main():
    client = CoinbaseClient(advanced=True, debug=True)
    accounts = client.fetch_advanced_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
