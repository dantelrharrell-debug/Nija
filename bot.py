import time
from coinbase.rest import RESTClient

API_KEY = "YOUR_COINBASE_API_KEY"
API_SECRET = "YOUR_COINBASE_API_SECRET"

def main():
    print("NIJA live trading bot logic is now running! Initializing Coinbase client...")

    client = RESTClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
    )

    product_id = "BTC-USD"

    while True:
        try:
            product = client.get_product(product_id)
            price = product.get('price', None)
            print(f"[NIJA] Current {product_id} price: ${price}")
            time.sleep(10)
        except Exception as e:
            print(f"[NIJA][ERROR] {str(e)}")
            time.sleep(10)

if __name__ == "__main__":
    main()
