from coinbase.rest import accounts
import os

print("Testing coinbase.rest.accounts module...\n")

print("Functions available:", dir(accounts))

print("\n--- Test: get_accounts() ---")
try:
    resp = accounts.get_accounts(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        api_passphrase=os.getenv("COINBASE_API_PASSPHRASE")  # may not be needed
    )
    print("RESPONSE TYPE:", type(resp))
    print("RESPONSE:", resp)
except Exception as e:
    print("ERROR calling get_accounts():", e)

print("\n--- Test: get_account (dummy UUID) ---")
try:
    resp = accounts.get_account(
        account_uuid="fake-uuid",
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
    )
    print("RESPONSE:", resp)
except Exception as e:
    print("Expected failure (bad uuid):", e)
