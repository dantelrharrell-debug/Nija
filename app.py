from nija_client import client       # or: from nija_client import CLIENT as client
from nija_orders import place_order, fetch_account_balance

import time

# Cache globals to avoid hammering API
_last_balance_fetch_ts = 0
_balance_cache_ttl = 30  # seconds between live balance fetches to respect rate limits

def _safe_getattr(obj, name):
    """Return attribute if exists else None (no exception)."""
    return getattr(obj, name) if obj is not None and hasattr(obj, name) else None

def fetch_account_balance(client, default_currency='USD'):
    """
    Attempt to fetch the total account balance in USD using the provided Coinbase client.
    Returns a float (USD total) or None if client is not attached / fetch failed.
    This function is defensive and will try several common client method names/formats.
    """
    global _last_balance_fetch_ts
    now = time.time()

    # Respect cache / rate-limit TTL
    if now - _last_balance_fetch_ts < _balance_cache_ttl:
        return None  # Caller should keep using previous account_balance

    if client is None:
        return None

    try:
        total_usd = 0.0
        # Try common 'get_accounts' or 'list_accounts' style methods
        accounts = None
        for fn in ("get_accounts", "list_accounts", "get_all_accounts", "accounts"):
            meth = _safe_getattr(client, fn)
            if callable(meth):
                try:
                    accounts = meth()
                    break
                except Exception:
                    # some libs require no args, others do; ignore and try next
                    continue
            # sometimes client.accounts is a property/list already
            if meth is not None and not callable(meth):
                accounts = meth
                break

        # If we got something that looks like accounts, normalize it to a list of dicts
        if accounts:
            # Some clients return a dict with 'data' key
            if isinstance(accounts, dict) and "data" in accounts and isinstance(accounts["data"], list):
                accounts = accounts["data"]

            # iterate accounts
            for acc in accounts:
                # support different shapes:
                # 1) acc['balance'] -> {'amount': '0.123', 'currency':'BTC'}
                # 2) acc['currency'], acc['balance']
                # 3) acc.balance.amount (object)
                try:
                    # dict-like
                    if isinstance(acc, dict):
                        if "balance" in acc and isinstance(acc["balance"], (dict, str)):
                            bal = acc["balance"]
                            # if nested dict with 'amount' and 'currency'
                            if isinstance(bal, dict) and "amount" in bal and "currency" in bal:
                                amount = float(bal["amount"])
                                currency = bal["currency"]
                            else:
                                # sometimes balance is string and currency is separate
                                amount = float(bal) if isinstance(bal, (int, float, str)) else 0.0
                                currency = acc.get("currency") or acc.get("asset") or acc.get("currency_code")
                        else:
                            # maybe top-level fields
                            amount = float(acc.get("amount") or acc.get("balance") or 0.0)
                            currency = acc.get("currency") or acc.get("asset") or acc.get("currency_code") or default_currency
                    else:
                        # object-like (SDK objects)
                        bal_obj = getattr(acc, "balance", None) or getattr(acc, "amount", None)
                        if bal_obj is not None and hasattr(bal_obj, "amount"):
                            amount = float(getattr(bal_obj, "amount"))
                            currency = getattr(bal_obj, "currency", None) or getattr(acc, "currency", default_currency)
                        else:
                            # fallback - skip
                            continue
                except Exception:
                    # skip malformed entry
                    continue

                currency = str(currency).upper()
                if currency in ("USD", "USDT", "USDC", "DAI"):
                    total_usd += amount
                    continue

                # Convert crypto amount to USD using spot price
                price = None
                # try common spot price methods
                for price_fn in ("get_spot_price", "get_spot_price_currency", "get_price", "get_ticker", "get_product_ticker", "ticker"):
                    pf = _safe_getattr(client, price_fn)
                    if callable(pf):
                        try:
                            # many clients expect product_id like "BTC-USD" or "BTC-USD"
                            product_id = f"{currency}-USD"
                            res = pf(product_id=product_id) if "product_id" in pf.__code__.co_varnames else pf(product_id)
                            # res can be dict or object: try extract a price field
                            if isinstance(res, dict):
                                # check common keys
                                price_val = res.get("price") or res.get("amount") or res.get("rate") or res.get("spot_price")
                                if price_val:
                                    price = float(price_val)
                                    break
                            else:
                                # object-like
                                if hasattr(res, "price"):
                                    price = float(getattr(res, "price"))
                                    break
                                # sometimes returns tuple/list
                                if isinstance(res, (list, tuple)) and len(res) >= 1:
                                    price = float(res[0])
                                    break
                        except Exception:
                            continue

                # If still no price from client, attempt a generic market-pricing call
                # (Some clients have client.get_product or client.market_data etc.)
                if price is None:
                    # best-effort: try client.get_product(product_id) -> may include 'price' or 'last'
                    fn = _safe_getattr(client, "get_product")
                    if callable(fn):
                        try:
                            product = fn(f"{currency}-USD")
                            if isinstance(product, dict):
                                price_val = product.get("price") or product.get("last") or product.get("spot_price")
                                if price_val:
                                    price = float(price_val)
                        except Exception:
                            pass

                # If we still couldn't get a price, skip this currency (conservative)
                if price is None:
                    # optionally you could assume a placeholder, but skipping is safer
                    print(f"fetch_account_balance: couldn't fetch price for {currency}, skipping conversion.")
                    continue

                total_usd += amount * price

            # record fetch timestamp and return
            _last_balance_fetch_ts = now
            return round(total_usd, 2)

        # If accounts not available, try single-account endpoints (some clients use get_account/balance)
        # e.g., client.get_account('USD') or client.get_account_balance()
        for single_fn in ("get_account", "get_balance", "get_all_balance", "account_balance", "balance"):
            fn = _safe_getattr(client, single_fn)
            if callable(fn):
                try:
                    res = fn()
                    # try to interpret res as dict or object
                    if isinstance(res, dict):
                        # sum fields if possible
                        if "balances" in res and isinstance(res["balances"], list):
                            # recursive handling not implemented here for brevity
                            break
                        # if res contains 'amount' and 'currency'
                        if "amount" in res and "currency" in res:
                            amt = float(res["amount"])
                            cur = str(res["currency"]).upper()
                            if cur == "USD":
                                _last_balance_fetch_ts = now
                                return round(amt, 2)
                    # else fallthrough
                except Exception:
                    continue

    except Exception as e:
        print("fetch_account_balance error:", e)

    return None
