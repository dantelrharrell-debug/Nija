# nija_balance_helper.py
from decimal import Decimal, InvalidOperation
import logging
from typing import Optional, Any

# Import your client factory (will return DummyClient or real client)
from nija_client import init_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_balance_helper")


def _iter_accounts_shape(obj: Any):
    """
    Yield account-like dicts from many shapes:
    - {'data': [...]} (Coinbase REST)
    - list/tuple of account dicts
    - object with .data or iterable attributes
    """
    # coinbase REST style: {'data': [...]}
    try:
        if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], (list, tuple)):
            for a in obj["data"]:
                yield a
            return
    except Exception:
        pass

    # list/tuple style
    if isinstance(obj, (list, tuple)):
        for a in obj:
            yield a
        return

    # object with .data attribute
    data = getattr(obj, "data", None)
    if isinstance(data, (list, tuple)):
        for a in data:
            yield a
        return

    # object is single account-like
    yield obj


def _account_currency_and_balance(a: Any):
    """
    Normalize account entries:
    returns tuple (currency_str, Decimal(amount)) or (None, None)
    Handles dicts and simple objects.
    """
    try:
        # coinbase REST: a['balance'] -> {'amount': '9.00', 'currency': 'USD'}
        if isinstance(a, dict):
            b = a.get("balance") or a.get("available") or {}
            if isinstance(b, dict):
                amt = b.get("amount") or b.get("value") or None
                cur = b.get("currency") or a.get("currency") or None
            else:
                # maybe balance is string
                amt = a.get("balance")
                cur = a.get("currency")
        else:
            # object with attributes
            bal = getattr(a, "balance", None)
            if isinstance(bal, dict):
                amt = bal.get("amount")
                cur = bal.get("currency")
            else:
                amt = getattr(a, "balance", None)  # fallback
                cur = getattr(a, "currency", None)

        if amt is None or cur is None:
            # some APIs store amount at a['amount'] and currency at a['currency']
            if isinstance(a, dict):
                amt = a.get("amount") or a.get("balance_amount")
                cur = a.get("currency") or a.get("asset")
            else:
                amt = amt or getattr(a, "amount", None)
                cur = cur or getattr(a, "asset", None)

        if amt is None or cur is None:
            return None, None

        # normalize string to Decimal
        try:
            return str(cur).upper(), Decimal(str(amt))
        except (InvalidOperation, ValueError):
            return str(cur).upper(), None
    except Exception:
        return None, None


def get_usd_balance_from_client(client) -> Decimal:
    """
    Given an instantiated client, try multiple common methods to find USD fiat balance.
    Returns Decimal(0) on failure.
    """
    try:
        # 1) Try explicit helper if client provides one
        if hasattr(client, "get_usd_balance") and callable(getattr(client, "get_usd_balance")):
            try:
                b = client.get_usd_balance()
                if b is None:
                    logger.debug("[NIJA-BALANCE] client.get_usd_balance() returned None")
                else:
                    return Decimal(str(b))
            except Exception as e:
                logger.debug(f"[NIJA-BALANCE] client.get_usd_balance() failed: {e}")

        # 2) Common account endpoints
        candidates = []
        for method in ("get_accounts", "get_spot_account_balances", "get_accounts_list", "get_all_accounts", "accounts"):
            try:
                attr = getattr(client, method, None)
                if callable(attr):
                    candidates.append(attr())
                elif attr is not None:
                    # attribute (like client.accounts) could be a list/obj
                    candidates.append(attr)
            except Exception as e:
                logger.debug(f"[NIJA-BALANCE] calling {method} raised: {e}")

        # Inspect all candidate results
        for cand in candidates:
            if cand is None:
                continue
            # log a short summary for debugging
            try:
                logger.debug(f"[NIJA-BALANCE] candidate shape type: {type(cand)}")
            except Exception:
                pass

            for acc in _iter_accounts_shape(cand):
                # log account raw (shortened)
                try:
                    logger.info(f"[NIJA-BALANCE] account entry (short): {str(acc)[:200]}")
                except Exception:
                    pass

                cur, amt = _account_currency_and_balance(acc)
                if cur == "USD" and amt is not None:
                    logger.info(f"[NIJA-BALANCE] Detected USD account -> {amt}")
                    return amt

        # 3) Last-resort: some APIs return a dict {'USD': amount}
        for cand in candidates:
            try:
                if isinstance(cand, dict) and "USD" in cand:
                    return Decimal(str(cand["USD"]))
            except Exception:
                continue

    except Exception as e:
        logger.exception(f"[NIJA-BALANCE] Unexpected error: {e}")

    logger.warning("[NIJA-BALANCE] No USD balance found; returning 0")
    return Decimal("0")


# Convenience wrapper to let other modules call without instantiating client
def get_usd_balance() -> Decimal:
    client = init_client()
    logger.info(f"[NIJA-BALANCE] Using client: {type(client).__name__}")
    return get_usd_balance_from_client(client)


# Debug CLI
if __name__ == "__main__":
    b = get_usd_balance()
    print(f"USD balance detected: {b}")
