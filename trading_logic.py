# trading_logic.py
import logging
from decimal import Decimal
from nija_client import client  # auto-attaches live client (or DummyClient)

logger = logging.getLogger("nija.app")

def place_order(symbol, trade_type, side, amount):
    """
    Places a live order if the Coinbase client is attached; otherwise returns a simulated order.
    Parameters:
      - symbol: str, e.g. "BTC-USD" or "BTC/USD" depending on your client
      - trade_type: str, e.g. "Spot" or "Futures" (passed through)
      - side: "buy" or "sell"
      - amount: numeric or string (converted to Decimal when possible)
    Returns:
      dict: response from live client or simulated order dict
    """
    try:
        # normalize amount to Decimal (safe)
        try:
            amount_dec = Decimal(str(amount))
        except Exception:
            logger.warning("[NIJA] Couldn't convert amount to Decimal, using raw value: %s", amount)
            amount_dec = amount

        # If a real client is attached and has place_order, attempt live order
        if client and hasattr(client, "place_order"):
            try:
                response = client.place_order(
                    symbol=symbol,
                    type=trade_type,
                    side=side,
                    amount=amount_dec
                )
                logger.info("[NIJA] Placed live order -> %s %s %s", side, amount_dec, symbol)
                return response
            except Exception as live_err:
                # Live order failed — log and fall back to simulated response
                logger.error("[NIJA] Live order failed for %s: %s -- falling back to simulation", symbol, live_err)

        # Fallback simulation (either no client or live order failed)
        simulated = {
            "symbol": symbol,
            "type": trade_type,
            "side": side,
            "amount": str(amount_dec),
            "status": "simulated"
        }
        logger.warning("[NIJA] place_order: client is None or failed -> simulated order returned for %s", symbol)
        return simulated

    except Exception as e:
        logger.exception("[NIJA] Unexpected error in place_order for %s: %s", symbol, e)
        return {
            "symbol": symbol,
            "type": trade_type,
            "side": side,
            "amount": str(amount),
            "status": "simulated_due_to_error",
            "error": str(e)
        }
