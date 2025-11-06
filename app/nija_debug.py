# nija_debug.py
import os
import sys
import json

# load .env if python-dotenv installed
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"ℹ️ Loaded environment variables from {env_path}")
    else:
        print("ℹ️ No .env file found; using system environment variables")
except Exception:
    print("⚠️ python-dotenv not available; using system environment variables")

print("ℹ️ Current working directory:", os.getcwd())
print("ℹ️ Files in project root:", sorted(os.listdir(".")))

# quick env check
required = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    print(f"❌ Missing required env vars: {', '.join(missing)}")
    sys.exit(1)
else:
    print("✅ Required environment variables are set.")

# import client
try:
    from nija_client import CoinbaseClient
    print("✅ Successfully imported CoinbaseClient")
except Exception as e:
    print("❌ ImportError:", e)
    sys.exit(1)

# attempt to list accounts and print helpful debug
try:
    client = CoinbaseClient()
    accounts = client.list_accounts()
    print("✅ CoinbaseClient instantiated.")
    print("Accounts:", json.dumps(accounts, indent=2) if accounts is not None else "None")
except Exception as e:
    # If requests not imported here, print general exception
    print("❌ Error initializing CoinbaseClient or fetching accounts:", str(e))
    # If requests is available, show more
    try:
        import requests
        # no-op - but if a response object exists within exception, not always accessible
    except Exception:
        pass
    sys.exit(1)

print("✅ Debug finished.")
