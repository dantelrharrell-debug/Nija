import os
import sys
import traceback
from coinbase.rest import RESTClient

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

    def list_portfolios(client):
        try:
            print("Fetching portfolios...")
            if hasattr(client, 'list_portfolios'):
                resp = client.list_portfolios()
            else:
                resp = client.get_portfolios()
            portfolios = getattr(resp, 'portfolios', [])
            print(f"Got {len(portfolios)} portfolios from API")
            return portfolios
        except Exception as e:
            print(f"get_portfolios error: {e}")
            traceback.print_exc()
            return []

    def list_accounts(client, uuid):
        try:
            if hasattr(client, 'list_accounts'):
                resp = client.list_accounts(portfolio_uuid=uuid)
            else:
                resp = client.get_accounts(retail_portfolio_id=uuid)
            return getattr(resp, 'accounts', [])
        except Exception as e:
            return f"(accounts error: {e})"

    portfolios = list_portfolios(client)
    if not portfolios:
        print("No portfolios returned.")
        return 0
    print(f"Found {len(portfolios)} portfolio(s):")
    for p in portfolios:
        uuid = getattr(p, 'uuid', getattr(p, 'retail_portfolio_id', None))
        name = getattr(p, 'name', None)
        print(f"- {name} UUID={uuid}")
        accs = list_accounts(client, uuid)
        if isinstance(accs, str):
            print(f"  {accs}")
            continue
        usd = sum(float(getattr(a, 'available_balance', getattr(a, 'balance', None)).value)
                  for a in accs if getattr(a, 'currency', None) == 'USD')
        usdc = sum(float(getattr(a, 'available_balance', getattr(a, 'balance', None)).value)
                   for a in accs if getattr(a, 'currency', None) == 'USDC')
        print(f"  USD=${usd:.2f} USDC=${usdc:.2f}")
    return 0
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
