# nija_debug.py
import os
import sys
import json

# attempt to load .env for local debugging (optional)
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"ℹ️ Loaded environment variables from {env_path}")
    else:
        print("ℹ️ No .env file found; using system environment variables")
except Exception:
    print("⚠️ python-dotenv missing or failed; using existing environment variables")

print("ℹ️ Current working directory:", os.getcwd())
print("ℹ️ Files in project root:", os.listdir("."))

# Import the client
try:
    from nija_client import CoinbaseClient
    print("✅ Successfully imported CoinbaseClient")
except Exception as e:
    print("❌ ImportError:", e)
    sys.exit(1)

def check_env():
    missing = []
    for k in ("COINBASE_API_KEY", "COINBASE_API_SECRET"):
        if not os.getenv(k):
            missing.append(k)
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}")
        return False
    # passphrase optional for Advanced API
    if not os.getenv("COINBASE_API_PASSPHRASE"):
        print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")
    return True

def run():
    if not check_env():
        return

    try:
        client = CoinbaseClient()
    except Exception as e:
        print("❌ Error initializing CoinbaseClient:", e)
        return

    print("ℹ️ Attempting to fetch accounts...")
    result = None
    try:
        result = client.get_accounts()
    except Exception as e:
        print("❌ Error calling get_accounts():", e)

    if result is None:
        print("Accounts: None (likely unauthorized, wrong base URL, or no permission).")
    else:
        # pretty print some info
        try:
            print("Accounts JSON summary:")
            if isinstance(result, dict):
                # show top-level keys and item count
                keys = list(result.keys())
                print("Top keys:", keys)
                # try to find data array
                data = result.get("data") or result.get("accounts") or result
                if isinstance(data, list):
                    print("accounts_count:", len(data))
                    # print the first account summary
                    if data:
                        print("first_account_preview:", json.dumps({
                            "id": data[0].get("id"),
                            "currency": data[0].get("currency") or data[0].get("currency_code"),
                            "balance": data[0].get("balance") or data[0].get("available_balance") or {}
                        }, default=str))
                else:
                    print(json.dumps(result, indent=2)[:2000])
            else:
                print(result)
        except Exception as e:
            print("❌ Error summarizing accounts:", e)
            print("raw result:", result)

if __name__ == "__main__":
    run()
