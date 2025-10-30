# signals.py
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signals")

def generate_signal(symbol, client=None):
    """
    Generates a trading signal for a symbol.
    If a client is provided, can access live data; otherwise, uses simulation.
    """
    try:
        if client:
            # Example: use client to fetch price or order book
            # Replace with your real logic
            logger.info(f"[NIJA] Generating signal for {symbol} using client")
            # sig = some_real_calculation(client, symbol)
            sig = "BUY"  # placeholder
        else:
            logger.info(f"[NIJA] Generating simulated signal for {symbol}")
            sig = "HOLD"  # simulation fallback
        return sig
    except Exception as e:
        logger.error(f"Error generating signal for {symbol}: {e}")
        return None
