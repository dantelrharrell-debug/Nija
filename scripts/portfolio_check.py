import os
import sys
import traceback
from coinbase.rest import RESTClient


def list_portfolios(client):
    try:
        print("Fetching portfolios...")
        if hasattr(client, "list_portfolios"):
            resp = client.list_portfolios()
        else:
            resp = client.get_portfolios()
        portfolios = getattr(resp, "portfolios", [])
        print(f"Got {len(portfolios)} portfolios from API")
        return portfolios
    except Exception as e:
        print(f"get_portfolios error: {e}")
        traceback.print_exc()
        return []


def list_accounts(client, uuid):
    try:
        if hasattr(client, "list_accounts"):
            resp = client.list_accounts(portfolio_uuid=uuid)
        else:
            resp = client.get_accounts(retail_portfolio_id=uuid)
        return getattr(resp, "accounts", [])
    except Exception as e:
        return f"(accounts error: {e})"


def _balance_value(account):
    balance_obj = getattr(account, "available_balance", getattr(account, "balance", None))
    return float(getattr(balance_obj, "value", 0.0)) if balance_obj else 0.0


def main():
    try:
        api_key = os.getenv("COINBASE_API_KEY")
        api_secret = os.getenv("COINBASE_API_SECRET")
        if not api_key or not api_secret:
            print("Missing COINBASE_API_KEY or COINBASE_API_SECRET")
            return 1

        print(f"Connecting with API key: {api_key[:50]}...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("Client created successfully")

        portfolios = list_portfolios(client)
        if not portfolios:
            print("No portfolios returned.")
            return 0

        print(f"Found {len(portfolios)} portfolio(s):")
        for portfolio in portfolios:
            uuid = getattr(portfolio, "uuid", getattr(portfolio, "retail_portfolio_id", None))
            name = getattr(portfolio, "name", None)
            print(f"- {name} UUID={uuid}")

            accounts = list_accounts(client, uuid)
            if isinstance(accounts, str):
                print(f"  {accounts}")
                continue

            usd = sum(_balance_value(a) for a in accounts if getattr(a, "currency", None) == "USD")
            usdc = sum(_balance_value(a) for a in accounts if getattr(a, "currency", None) == "USDC")
            print(f"  USD=${usd:.2f} USDC=${usdc:.2f}")

        return 0
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
