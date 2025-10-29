# trading_logic.py
import logging
from decimal import Decimal
from nija_client import client  # global client from nija_client.py

logger = logging.getLogger("nija.app")

def place_order(symbol, trade_type, side, amount):
    """
    Places a live order if the Coinbase client is attached; otherwise returns a simulated order.
    """
    try:
        # normalize amount
        try:
            amount_dec = Decimal(str(amount))
        except Exception:
            logger.warning("[NIJA] Couldn't convert amount to Decimal, using raw value: %s", amount)
            amount_dec = amount

        # Try live order if client supports it
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
                logger.error("[NIJA] Live order failed for %s: %s -- falling back to simulation", symbol, live_err)

        # Fallback simulation
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
