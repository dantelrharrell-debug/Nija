# app.py (patched)

from nija_client import client  # your live Coinbase client
from trading_logic import generate_signal
import logging

logger = logging.getLogger("nija.app")

def update_positions_and_signals(symbols, client=None):
    """
    Updates trading positions and generates signals for all symbols.
    Accepts optional client for live trading.
    """
    results = {}

    for symbol in symbols:
        try:
            sig = generate_signal(symbol, client=client)
            results[symbol] = sig
            logger.info(f"[update_positions] {symbol}: {sig}")
        except Exception as e:
            logger.error(f"generate_signal error for {symbol}: {e}", exc_info=True)
            results[symbol] = None  # failed signal

    return results

def fetch_account_balance(client=None):
    """
    Fetches account balance if client is available.
    """
    if client is None:
        logger.info("fetch_account_balance: client is None -> skipping live fetch")
        return {}
    try:
        balance = client.get_account_balance()
        logger.info(f"Account balance fetched: {balance}")
        return balance
    except Exception as e:
        logger.error(f"fetch_account_balance error: {e}")
        return {}
