from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient(debug=True)
    accounts = client.fetch_accounts()
    print("Fetched accounts:", accounts)

if __name__ == "__main__":
    main()
