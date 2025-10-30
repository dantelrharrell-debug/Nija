import os
import logging
import time
from decimal import Decimal

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# --- Try importing Coinbase client ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Coinbase client available")
except ModuleNotFoundError:
    logger.warning("[NIJA] Coinbase client not found, using DummyClient")

# --- Dummy client ---
class DummyClient:
    def get_account(self, currency):
        return {"balance": 1000.0}  # simulate $1000

    def buy(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated BUY {{'amount': {amount}, 'product_id': '{product_id}'}}")

    def sell(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated SELL {{'amount': {amount}, 'product_id': '{product_id}'}}")

# --- Initialize client ---
if CoinbaseClient and os.getenv("TRADING_MODE") == "live":
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        api_passphrase=os.getenv("COINBASE_API_PASSPHRASE")
    )
    logger.info("[NIJA] Live trading client initialized")
else:
    client = DummyClient()
    logger.warning("[NIJA] Trading in simulation mode")

# --- Position sizing ---
def get_position_size(account_balance):
    """Use 2%–10% of equity per trade, aggressive but safe."""
    min_pct, max_pct = Decimal("0.02"), Decimal("0.10")
    trade_pct = max_pct  # always go aggressive by default
    return round(account_balance * trade_pct, 2)

# --- Simple strategy (price threshold example) ---
def check_signal(price):
    """Return True to buy, False to skip."""
    # Example: buy only if BTC < $30,000 (replace with your own logic)
    return price < 30000

# --- Trading loop ---
def start_trading():
    product = "BTC-USD"
    logger.info("[NIJA] Trading loop started...")

    def loop():
        while True:
            # --- Get account balance ---
            balance_info = client.get_account("USD")
            balance = Decimal(balance_info.get("balance", 0))

            # --- Get current price ---
            # DummyClient doesn't have price API, replace with real API call in live mode
            price = Decimal("29500") if isinstance(client, DummyClient) else client.get_product_price(product)

            # --- Check trading signal ---
            if check_signal(price):
                amount_usd = get_position_size(balance)
                amount_btc = amount_usd / price
                client.buy(product_id=product, amount=float(amount_btc))
                logger.info(f"[NIJA] BUY executed: {amount_btc:.6f} BTC @ ${price}")
            else:
                logger.info(f"[NIJA] No signal, price at ${price}")

            time.sleep(10)  # adjust interval as needed

    import threading
    t = threading.Thread(target=loop, daemon=True)
    t.start()
