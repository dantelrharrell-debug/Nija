import time
from coinbase.rest import RESTClient

API_KEY = "YOUR_COINBASE_API_KEY"
API_SECRET = "YOUR_COINBASE_API_SECRET"
API_BASE_URL = "https://api.coinbase.com"

def main():
    print("NIJA live trading bot logic is now running! Initializing Coinbase client...")

    client = RESTClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_url=API_BASE_URL,
    )

    product_id = "BTC-USD"

    while True:
        try:
            ticker = client.get_product_ticker(product_id)
            price = ticker['price'] if 'price' in ticker else ticker.get('price', None)
            print(f"[NIJA] Current {product_id} price: ${price}")
            time.sleep(10)
        except Exception as e:
            print(f"[NIJA][ERROR] {str(e)}")
            time.sleep(10)

if __name__ == "__main__":
    main()
