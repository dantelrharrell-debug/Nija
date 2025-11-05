from nija_client import CoinbaseClient, calculate_position_size

def main():
    try:
        client = CoinbaseClient()
        usd_balance = client.get_usd_spot_balance()
        print(f"💰 USD Spot Balance: ${usd_balance:.2f}")

        # Example position sizing
        if usd_balance > 0:
            trade_size = calculate_position_size(usd_balance, risk_factor=5)
            print(f"📊 Suggested Trade Size: ${trade_size:.2f}")
        else:
            print("⚠️ Account balance is 0, cannot calculate position size.")

    except Exception as e:
        print(f"❌ Error in Nija debug: {e}")


if __name__ == "__main__":
    main()
