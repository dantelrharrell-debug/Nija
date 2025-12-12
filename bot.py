import time
from coinbase.rest import RESTClient

# TODO: Replace with your actual Coinbase API credentials!
API_KEY = "YOUR_COINBASE_API_KEY"
API_SECRET = "YOUR_COINBASE_API_SECRET"
API_PASSPHRASE = "YOUR_COINBASE_API_PASSPHRASE"
API_BASE_URL = "https://api.coinbase.com"

def main():
    print("NIJA live trading bot logic is now running! Initializing Coinbase client...")

    client = RESTClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE,
        api_url=API_BASE_URL,
    )

    product_id = "BTC-USD"

    while True:
        try:
            # Example: fetch the latest price for BTC-USD
            ticker = client.get_product_ticker(product_id)
            price = ticker['price'] if 'price' in ticker else ticker.get('price', None)
            print(f"[NIJA] Current {product_id} price: ${price}")

            # Example strategy logic: (placeholder, does NOT trade by default)
            # Uncomment and implement your trade logic here!
            #
            # if some_condition:
            #     response = client.place_order(
            #         product_id=product_id,
            #         side='buy',  # 'sell' for selling
            #         order_type='market',
            #         size='0.001',  # for example, buy 0.001 BTC
            #     )
            #     print(f"[NIJA] Order placed: {response}")

            # Wait before next cycle (adjust as needed)
            time.sleep(10)
        except Exception as e:
            print(f"[NIJA][ERROR] {str(e)}")
            time.sleep(10)

if __name__ == "__main__":
    main()
