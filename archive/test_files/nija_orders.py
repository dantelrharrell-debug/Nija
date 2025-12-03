# nija_orders.py
"""
Defensive order & balance helpers for Nija.
Drop this file next to nija_client.py and app.py, then import functions in app.py:
    from nija_client import client
    from nija_orders import place_order, fetch_account_balance
"""

import time
import logging

# logger for orders/balance helpers
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("nija.orders")

# TTL for balance fetch caching (seconds)
_last_balance_fetch_ts = 0
_balance_cache_ttl = 30

def place_order(symbol, market_type, side, amount, client=None):
    """
    Defensive placement: tries common method names on the attached client.
    - symbol: 'BTC/USD' or 'BTC-USD' (we normalize)
    - side: 'buy' or 'sell' (lowercase expected)
    - amount: USD amount (client-specific; adapt if needed)
    Returns dict with status and order info.
    """
    _logger.info("place_order called -> symbol=%s, type=%s, side=%s, amount=%s, client_attached=%s", symbol, market_type, side, amount, client is not None)
    if client is None:
        _logger.info("place_order: client is None -> returning simulated order")
        return {"status": "simulated", "order": {"symbol": symbol, "side": side, "amount": amount}}

    # Normalize symbol into commonly-used product id formats
    product_id_dash = symbol.replace("/", "-")
    product_id_slash = symbol.replace("-", "/")

    # Candidate method names & kwargs (adjust these if your client uses different arg names)
    candidate_methods = [
        ("place_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("create_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("submit_order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
        ("order", {"product_id": product_id_dash, "side": side.lower(), "size": str(amount), "type": "market"}),
    ]

    for fn_name, kwargs in candidate_methods:
        fn = getattr(client, fn_name, None)
        if callable(fn):
            try:
                _logger.info("Attempting client.%s with args %s", fn_name, kwargs)
                order = fn(**kwargs)
                _logger.info("place_order: client.%s successful -> %s", fn_name, order)
                return {"status": "ok", "order": order}
            except TypeError:
                # maybe method expects positional args; try a positional attempt
                try:
                    order = fn(kwargs.get("product_id"), kwargs.get("side"), kwargs.get("size"))
                    _logger.info("place_order: client.%s (positional) successful -> %s", fn_name, order)
                    return {"status": "ok", "order": order}
                except Exception as e:
                    _logger.exception("place_order: client.%s positional failed: %s", fn_name, e)
                    continue
            except Exception as e:
                _logger.exception("place_order: client.%s error: %s", fn_name, e)
                continue

    # If we've tried common methods and nothing worked, return error
    _logger.error("place_order: no known order method succeeded on client.")
    return {"status": "error", "error": "no_known_order_method_on_client"}


def fetch_account_balance(client, default_currency='USD'):
    """
    Defensive account balance fetch:
    - tries common client.get_accounts/list_accounts methods
    - converts non-USD assets to USD using client spot price helpers (if available)
    - returns float USD total or None if it can't fetch
    Uses internal TTL to avoid hitting rate limits.
    """
    global _last_balance_fetch_ts
    now = time.time()
    if now - _last_balance_fetch_ts < _balance_cache_ttl:
        # respect TTL: return None to indicate "no new value" (caller should keep last known balance)
        return None

    if client is None:
        _logger.info("fetch_account_balance: client is None -> skipping live fetch")
        return None

    try:
        res = None
        for fn in ("get_accounts", "list_accounts", "get_all_accounts", "accounts"):
            meth = getattr(client, fn, None)
            if callable(meth):
                try:
                    res = meth()
                    break
                except Exception as e:
                    _logger.debug("fetch_account_balance: client.%s raised %s", fn, e)
                    continue
            # if attribute exists but not callable, treat it as data
            if meth is not None:
                res = meth
                break

        if not res:
            _logger.warning("fetch_account_balance: no accounts-like response from client.")
            return None

        # Normalize response (dict with data[] vs list)
        accounts = res.get("data") if isinstance(res, dict) and "data" in res else res

        total_usd = 0.0
        for acc in accounts:
            try:
                # dict-like
                if isinstance(acc, dict):
                    bal = acc.get("balance") or acc.get("available") or acc.get("amount")
                    if isinstance(bal, dict) and "amount" in bal and "currency" in bal:
                        amount = float(bal["amount"])
                        currency = bal["currency"].upper()
                    else:
                        amount = float(bal)
                        currency = acc.get("currency", default_currency).upper()
                else:
                    # object-like
                    bal_obj = getattr(acc, "balance", None) or getattr(acc, "amount", None)
                    if bal_obj is not None and hasattr(bal_obj, "amount"):
                        amount = float(getattr(bal_obj, "amount"))
                        currency = getattr(bal_obj, "currency", default_currency).upper()
                    else:
                        # Unknown format; skip
                        continue

                if currency in ("USD", "USDC", "USDT", "DAI"):
                    total_usd += amount
                    continue

                # fetch spot price
                price = None
                for price_fn_name in ("get_spot_price", "get_price", "get_ticker", "get_product_ticker", "ticker"):
                    pf = getattr(client, price_fn_name, None)
                    if callable(pf):
                        try:
                            product = f"{currency}-USD"
                            out = None
                            try:
                                out = pf(product_id=product)
                            except TypeError:
                                out = pf(product)
                            if isinstance(out, dict):
                                price_val = out.get("price") or out.get("amount") or out.get("last")
                                if price_val:
                                    price = float(price_val)
                                    break
                            else:
                                if hasattr(out, "price"):
                                    price = float(out.price)
                                    break
                                if isinstance(out, (list, tuple)) and len(out) > 0:
                                    price = float(out[0])
                                    break
                        except Exception:
                            continue

                if price is None:
                    _logger.warning("fetch_account_balance: couldn't get price for %s, skipping conversion", currency)
                    continue
                total_usd += amount * price
            except Exception as e:
                _logger.exception("fetch_account_balance: error parsing account entry: %s", e)
                continue

        _last_balance_fetch_ts = now
        return round(total_usd, 2)
    except Exception as e:
        _logger.exception("fetch_account_balance top-level error: %s", e)
        return None
