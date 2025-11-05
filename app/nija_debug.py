from nija_client import CoinbaseClientWrapper as CoinbaseClient

def main():
    try:
        client = CoinbaseClient()
        print("✅ CoinbaseClient initialized successfully.")
        funded_account = client.get_funded_account()
        if funded_account:
            print(f"💰 Funded account: {funded_account['currency']} - {funded_account['balance']['amount']}")
        else:
            print("⚠️ No funded account found.")
    except Exception as e:
        print(f"❌ Error creating CoinbaseClient: {e}")

if __name__ == "__main__":
    main()
