# balance_helper.py
import logging
from decimal import Decimal

logger = logging.getLogger("nija_worker")

def get_usd_balance(client):
    """
    Fetch USD balance from Coinbase account.
    Works with no-passphrase accounts using standard REST API.
    Returns Decimal(0) if fetch fails.
    """
    try:
        if hasattr(client, "get_spot_account_balances"):
            balances = client.get_spot_account_balances()
            return Decimal(str(balances.get("USD", 0)))
        if hasattr(client, "get_account_balances"):
            balances = client.get_account_balances()
            return Decimal(str(balances.get("USD", 0)))
        if hasattr(client, "get_accounts"):
            accs = client.get_accounts()
            for a in accs:
                currency = a.get("currency") if isinstance(a, dict) else getattr(a, "currency", None)
                avail = a.get("available_balance") if isinstance(a, dict) else getattr(a, "available_balance", None)
                if str(currency).upper() in ("USD", "USDC"):
                    return Decimal(str(avail or 0))
    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
    return Decimal("0")
