# --- trading_logic.py ---

import logging

def generate_signal(symbol, client=None):
    """
    Generate a trading signal for a given symbol.
    Accepts optional client for live data or order execution.
    """
    signal = None

    if client is not None:
        try:
            # Fetch live market data
            market_data = client.get_market_data(symbol)  # adjust based on your API
            price = market_data.get("price")
            moving_average = market_data.get("moving_average")

            if price is not None and moving_average is not None:
                signal = "BUY" if price < moving_average else "SELL"
            else:
                signal = "HOLD"
        except Exception as e:
            logging.error(f"[generate_signal] client error for {symbol}: {e}")
            signal = "HOLD"
    else:
        # Dry-run / no client available
        signal = "HOLD"

    return signal
