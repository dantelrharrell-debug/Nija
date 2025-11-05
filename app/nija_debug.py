from nija_client import CoinbaseClient, calculate_position_size

def main():
    try:
        client = CoinbaseClient()
    except Exception as e:
        print(f"❌ Error creating CoinbaseClient: {e}")
        return

    acct = client.get_funded_account()
    if not acct:
        print("⚠️ No funded accounts found. Please fund a Coinbase account.")
        return

    currency = acct.get("currency")
    balance = float(acct.get("balance", {}).get("amount", 0))
    print(f"✅ Using funded account: {currency} with balance {balance}")

    trade_size = calculate_position_size(balance, risk_factor=5)  # Example risk factor
    print(f"💰 Calculated position size: {trade_size} {currency}")

if __name__ == "__main__":
    main()
