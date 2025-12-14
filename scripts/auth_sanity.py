import os
import sys

def main() -> int:
    print("Auth sanity: checking environment and SDK path...")
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    pem_content = os.getenv("COINBASE_PEM_CONTENT")
    pem_path = os.getenv("COINBASE_PEM_PATH")

    if not api_key or not api_secret:
        print("Missing COINBASE_API_KEY or COINBASE_API_SECRET")
        print("Tip: Set Cloud API credentials from cloud.coinbase.com/access/api")
        return 1

    print(f"KEY length: {len(api_key)}; SECRET length: {len(api_secret)}")
    if pem_content or pem_path:
        print("Warning: PEM-related envs detected. This can force PEM/JWT mode and cause failures.")
        print("- COINBASE_PEM_CONTENT set? ", bool(pem_content))
        print("- COINBASE_PEM_PATH set? ", bool(pem_path))
        print("Recommendation: Unset PEM envs to use Cloud API key+secret auth.")

    # Try importing SDK and listing portfolios without triggering PEM
    try:
        from coinbase.rest import RESTClient
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        # Prefer list_portfolios if available
        if hasattr(client, 'list_portfolios'):
            resp = client.list_portfolios()
        else:
            resp = client.get_portfolios()
        portfolios = getattr(resp, 'portfolios', [])
        print(f"SDK OK. Portfolios returned: {len(portfolios)}")
        for p in portfolios:
            uuid = getattr(p, 'uuid', getattr(p, 'retail_portfolio_id', None))
            name = getattr(p, 'name', None)
            print(f"- {name} UUID={uuid}")
        return 0
    except Exception as e:
        print("SDK call failed.")
        print(f"Error: {e}")
        # Heuristic hints
        msg = str(e)
        if "Unable to load PEM file" in msg or "MalformedFraming" in msg:
            print("Hint: PEM mode detected. Unset COINBASE_PEM_CONTENT/COINBASE_PEM_PATH and use Cloud API secret.")
        elif "403" in msg or "PERMISSION" in msg:
            print("Hint: Permission issue. Verify API key scopes and that it's an Advanced Trade key.")
        else:
            print("Hint: Double-check API key/secret values and environment setup.")
        print("Action: Ensure credentials are from cloud.coinbase.com/access/api and PEM envs are unset.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
