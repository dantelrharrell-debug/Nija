"""
Simple Alpaca API Test
Uses the exact code provided for testing Alpaca paper trading
"""

import alpaca_trade_api as tradeapi

# Alpaca API credentials
API_KEY = "PKS2NORMEX6BMN6P3T63C7ICZ2"
API_SECRET = "GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
BASE_URL = "https://paper-api.alpaca.markets/v2"

# Initialize API connection
api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

# Example: Get account information
account = api.get_account()
print(account)

# Example: Get list of positions
positions = api.list_positions()
for position in positions:
    print(position)
