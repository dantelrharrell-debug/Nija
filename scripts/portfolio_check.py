import os
from coinbase.rest import RESTClient

def main():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        print("Missing COINBASE_API_KEY or COINBASE_API_SECRET"); return 1
    client = RESTClient(api_key=api_key, api_secret=api_secret)

    def list_portfolios(client):
        try:
            if hasattr(client, 'list_portfolios'):
                resp = client.list_portfolios()
            else:
                resp = client.get_portfolios()
            return getattr(resp, 'portfolios', [])
        except Exception as e:
            print(f"get_portfolios error: {e}")
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

if __name__ == "__main__":
    raise SystemExit(main())
