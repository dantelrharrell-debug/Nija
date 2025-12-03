# nija_debug.py
import os, sys
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"ℹ️ Loaded environment variables from {env_path}")
    else:
        print("ℹ️ No .env file found; using system environment variables")
except Exception:
    print("⚠️ python-dotenv not available or failed; continuing without it")

print("ℹ️ Current working directory:", os.getcwd())
print("ℹ️ Files in project root:", sorted(os.listdir(".")))

# Import client and run a safe accounts check
try:
    from nija_client import CoinbaseClient
    print("✅ Successfully imported CoinbaseClient")
except Exception as e:
    print("❌ ImportError:", e)
    sys.exit(1)

# Basic env check
required = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    print("❌ Missing required environment variables:", missing)
else:
    if not os.getenv("COINBASE_API_PASSPHRASE"):
        print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")
    print("✅ Required environment variables are set.")

# Attempt accounts fetch
import requests
try:
    client = CoinbaseClient()
    print("ℹ️ Attempting to fetch accounts...")
    result = client.get_accounts()
    if result is None:
        print("Accounts JSON summary:")
        print({
            "ok": False,
            "url": os.getenv("COINBASE_API_BASE", "https://api.coinbase.com") + "/v2/accounts",
            "status": 401,
            "payload": "Unauthorized"
        })
    elif isinstance(result, dict) and result.get("ok") is False:
        print("Error fetching accounts:", result["status"], result.get("payload"))
    else:
        # Pretty lightweight summary
        try:
            if isinstance(result, dict) and "data" in result and isinstance(result["data"], list):
                print("Accounts: count =", len(result["data"]))
                if len(result["data"]) > 0:
                    print("First account keys:", list(result["data"][0].keys())[:8])
            else:
                print("Accounts result keys:", list(result.keys())[:8] if isinstance(result, dict) else str(type(result)))
        except Exception as e:
            print("Accounts parsing error:", e)
except requests.exceptions.RequestException as e:
    print("Network/Request exception while fetching accounts:", e)
except Exception as e:
    print("❌ Error initializing CoinbaseClient or fetching accounts:", type(e).__name__, str(e))
