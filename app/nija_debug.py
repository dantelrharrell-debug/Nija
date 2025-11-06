from nija_client import CoinbaseClientWrapper as CoinbaseClient

client = CoinbaseClient()
print(client.get_accounts())
