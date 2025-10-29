# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Initialize client ---
client = None

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if API_KEY and API_SECRET:
    try:
        from coinbase_advanced_py.client import CoinbaseClient
        client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("[NIJA] CoinbaseClient attached -> LIVE TRADING ENABLED")
    except ModuleNotFoundError:
        logger.warning("[NIJA] CoinbaseClient library not found. Using simulated mode")
        client = None
else:
    logger.warning("[NIJA] API keys missing. Using simulated mode")

# --- Wrapper functions ---
def place_order(symbol, side, amount, order_type="Spot"):
    """
    symbol: str, e.g., "BTC/USD"
    side: str, "buy" or "sell"
    amount: float
    order_type: str, "Spot" or "Futures"
    """
    global client

    if client:
        logger.info(f"[NIJA] place_order -> symbol={symbol}, type={order_type}, side={side}, amount={amount}, client_attached=True")
        return client.place_order(symbol=symbol, side=side, amount=amount, order_type=order_type)
    else:
        logger.info(f"[NIJA] place_order -> symbol={symbol}, type={order_type}, side={side}, amount={amount}, client_attached=False")
        logger.info("[NIJA] Simulated order returned")
        return {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "type": order_type,
            "simulated": True
        }

def fetch_account_balance():
    global client
    if client:
        return client.get_accounts()
    else:
        logger.info("[NIJA] fetch_account_balance: client is None -> skipping live fetch")
        return None
