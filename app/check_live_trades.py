from nija_client import CoinbaseClient
import logging

logging.basicConfig(level=logging.INFO)

client = CoinbaseClient()

# --- Check Open Orders ---
open_orders = client.fetch_open_orders()
logging.info("🔹 Open Orders:")
for order in open_orders:
    logging.info(f"  - {order['product_id']} | {order['side']} | {order['size']} @ {order['price']} | Status: {order['status']}")

# --- Check Recent Fills ---
fills = client.fetch_fills()  # last executed trades
logging.info("🔹 Recent Fills:")
for fill in fills[:10]:  # show last 10 fills
    logging.info(f"  - {fill['product_id']} | {fill['side']} | {fill['size']} @ {fill['price']} | Fee: {fill['fee']}")
