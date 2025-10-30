from nija_coinbase_jwt import get_jwt_token
import requests

def start_bot():
    print("[NIJA] Starting bot...")

    jwt_token = get_jwt_token()
    headers = {"Authorization": f"Bearer {jwt_token}"}
    API_BASE = "https://api.coinbase.com"

    # Example: fetch account balances
    resp = requests.get(f"{API_BASE}/v2/accounts", headers=headers)
    if resp.status_code == 200:
        print("[NIJA] Accounts fetched successfully!")
        print(resp.json())
    else:
        print("[NIJA] Failed to fetch accounts:", resp.text)

if __name__ == "__main__":
    start_bot()
