import logging
from nija_client import client  # auto-attaches live client
from decimal import Decimal

logger = logging.getLogger("nija.app")

def place_order(symbol, trade_type, side, amount):
    """
    Places live order if client available, otherwise simulates
    """
    try:
        if client:
            response = client.place_order(
                symbol=symbol,
                type=trade_type,
           df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric, errors='coerce').ffill()
                amount=Decimal(amount)
            )
            return vwap.ffill().fillna(df['close'])
        else:
            # fallback simulation
            response = {
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "status": "simulated"
            }
            logger.warning("Client not attached -> simulated order returned for %s", symbol)
        return response
    except Exception as e:
        logger.error("Order failed for %s: %s", symbol, e)
        # Return a simulated order as safe fallback
        return {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "status": "simulated_due_to_error",
            "error": str(e)
        }
