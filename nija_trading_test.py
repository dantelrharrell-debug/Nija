from vendor.coinbase_advanced_py.client import CoinbaseClient
import os

client = CoinbaseClient(
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
    passphrase=os.getenv("API_PASSPHRASE"),
    sandbox=False  # Must be False for live
)

print(client.get_accounts())  # Should return your live account balances
