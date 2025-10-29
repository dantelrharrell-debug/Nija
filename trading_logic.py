from nija_client import client
import logging

logger = logging.getLogger("nija.app")

def place_order(symbol, type, side, amount, client_override=None):
    """
    Places an order on Coinbase. Falls back to simulation if client is not available.
    """
    actual_client = client_override or client
    if actual_client:
        try:
            # Replace with your actual client order call
            response = actual_client.place_order(symbol=symbol, type=type, side=side, amount=amount)
            logger.info(f"[NIJA] Live order executed -> symbol={symbol}, type={type}, side={side}, amount={amount}")
            return response
        except Exception as e:
            logger.error(f"[NIJA] Live order failed, simulating instead: {e}")
    
    # Simulation fallback
    logger.info(f"[NIJA] place_order called -> symbol={symbol}, type={type}, side={side}, amount={amount}, client_attached=False")
    logger.info("[NIJA] place_order: client is None -> simulated order returned")
    return {
        "symbol": symbol,
        "type": type,
        "side": side,
        "amount": amount,
        "status": "simulated"
    }
