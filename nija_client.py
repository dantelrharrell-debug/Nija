# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Initialize Coinbase client ---
client = None
client_attached = False

try:
    from coinbase_advanced_py.client import CoinbaseClient

    # Load API credentials from environment variables
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    passphrase = os.getenv("COINBASE_PASSPHRASE")

    if not all([api_key, api_secret, passphrase]):
        raise ValueError("Coinbase API keys are not fully set in environment variables.")

    # Initialize live client
    client = CoinbaseClient(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )
    client_attached = True
    logger.info("[NIJA] CoinbaseClient initialized successfully -> LIVE TRADING ENABLED")

except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not installed. Using simulated client only.")
except Exception as e:
    client = None
    client_attached = False
    logger.warning(f"[NIJA] CoinbaseClient NOT initialized -> SIMULATED TRADING ONLY: {e}")


# --- Utility functions to handle orders safely ---
def place_order(symbol, side, type_, amount):
    """
    Place a live order if client attached, else simulate.
    """
    if client_attached and client is not None:
        logger.info(f"Placing LIVE order: {side} {amount} {symbol} ({type_})")
        return client.place_order(symbol=symbol, side=side, type=type_, amount=amount)
    else:
        logger.info(f"Simulated order: {side} {amount} {symbol} ({type_}) -> client not attached")
        return {
            "symbol": symbol,
            "side": side,
            "type": type_,
            "amount": amount,
            "simulated": True
        }


def get_account_balance():
    """
    Fetch live account balance if client attached, else return None.
    """
    if client_attached and client is not None:
        try:
            return client.get_accounts()
        except Exception as e:
            logger.error(f"Failed to fetch live balance: {e}")
            return None
    else:
        logger.info("Skipping live balance fetch -> client not attached")
        return None


# --- Quick check ---
if client_attached:
    logger.info("Client attached ✅ Ready for LIVE trading")
else:
    logger.warning("Client not attached ⚠️ Orders will be simulated")
