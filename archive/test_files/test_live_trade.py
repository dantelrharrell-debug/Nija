from nija_client import CoinbaseClient

client = CoinbaseClient()
symbol = "BTC-USD"
amount_usd = 1  # minimal safe test

order = client.place_market_order(symbol=symbol, side="buy", funds=amount_usd)
print("Test order response:", order)
