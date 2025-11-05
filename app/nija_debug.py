from nija_client import CoinbaseClient, calculate_position_size

def main():
    client = CoinbaseClient()
    funded_account = client.get_funded_account()
    if not funded_account:
        print("⚠️ No funded accounts found. Fund your Coinbase account.")
        return

    balance = float(funded_account.get("balance", {}).get("amount", 0))
    print(f"✅ Funded account: {funded_account.get('currency')}, balance: {balance}")
    trade_size = calculate_position_size(balance, risk_factor=5)
    print(f"💰 Calculated trade size: {trade_size}")

if __name__ == "__main__":
    main()
