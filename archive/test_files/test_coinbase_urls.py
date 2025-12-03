import requests
import os

# Use your existing API key / secret (if needed for Bearer auth)
API_KEY = os.getenv("COINBASE_API_KEY")
HEADERS = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}

# Candidate base URLs your bot has tried
BASE_URLS = [
    "https://api.cdp.coinbase.com",          # Advanced / Business
    "https://api.cdp.coinbase.com/accounts",
    "https://api.cdp.coinbase.com/brokerage/accounts",
    "https://api.cdp.coinbase.com/api/v3/trading/accounts",
    "https://api.cdp.coinbase.com/api/v3/portfolios",
    "https://api.coinbase.com",              # Standard API
    "https://api.coinbase.com/v2/accounts",
]

for url in BASE_URLS:
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        status = response.status_code
        print(f"[{status}] {url}")
        if status == 200:
            print("  ✅ Endpoint reachable, response sample:", response.json())
    except Exception as e:
        print(f"[ERROR] {url} -> {e}")
