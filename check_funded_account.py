# check_funded_account.py
from app.nija_client import CoinbaseClient

# Minimum balance to consider "funded"
FUND_THRESHOLD = 1.0

def main():
    client = CoinbaseClient()
    try:
        accounts = client.get_accounts()
    except Exception as e:
        print(f"Failed to fetch accounts: {e}")
        return

    funded_accounts = []
    for acct in accounts:
        name = acct.get("name", "Unnamed")
        balance_info = acct.get("balance", {})
        amount = float(balance_info.get("amount", 0))
        currency = balance_info.get("currency", "USD")
        if amount >= FUND_THRESHOLD:
            funded_accounts.append((name, amount, currency))

    if funded_accounts:
        print("Funded accounts detected:")
        for name, amount, currency in funded_accounts:
            print(f" - {name}: {amount} {currency}")
    else:
        print("No funded accounts detected!")

if __name__ == "__main__":
    main()
