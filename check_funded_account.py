#!/usr/bin/env python3
from nija_client import CoinbaseClient

def main():
    client = CoinbaseClient()

    try:
        accounts = client.get_all_accounts()
    except Exception as e:
        print(f"❌ Failed to fetch accounts: {e}")
        return

    funded_accounts = [
        acc for acc in accounts
        if float(acc.get('balance', {}).get('amount', 0)) > 0
    ]

    if not funded_accounts:
        print("⚠️ No funded accounts found. Fund your Coinbase account.")
        return

    print("✅ Funded accounts visible to this API key:")
    for acc in funded_accounts:
        currency = acc['currency']
        balance = acc['balance']['amount']
        account_type = acc.get('type', 'unknown')
        print(f"- {currency}: {balance} ({account_type})")

    # Pick the first funded account as default for Nija
    main_account = funded_accounts[0]
    print(f"\n🎯 Nija will trade from: {main_account['currency']} with balance {main_account['balance']['amount']}")

if __name__ == "__main__":
    main()
