# test_balance.py
from nija_client import client
from nija_orders import fetch_account_balance

if client:
    balance = fetch_account_balance(client)
    print("Live account balance:", balance)
else:
    print("Simulation mode active, cannot fetch balance.")
