# test_coinbase_client.py
import importlib.util, pathlib, json, sys

# Explicitly load the file /app/nija_hmac_client.py to avoid name collisions
spec = importlib.util.spec_from_file_location("nija_hmac_client", "/app/nija_hmac_client.py")
nija_hmac_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nija_hmac_client)

CoinbaseClient = nija_hmac_client.CoinbaseClient
print("Using CoinbaseClient from module:", CoinbaseClient.__module__)
print("Module file path:", pathlib.Path(nija_hmac_client.__file__).resolve())

client = CoinbaseClient()
status, data = client.get_accounts()
print("Status:", status)
print(json.dumps(data, indent=2) if isinstance(data, dict) else data)
