#!/usr/bin/env python3
# debug_client_full.py
import sys, os, json, traceback
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

from nija_client import client  # uses your attached client

print("=== DEBUG CLIENT FULL ===")
print("client is None?", client is None)
print("client repr:", repr(client))
print("client type:", type(client))

# Print available attributes/method names of the client (helps find correct methods)
try:
    attrs = sorted([a for a in dir(client) if not a.startswith("_")])
    print("\n--- client attrs (sample) ---")
    print(", ".join(attrs[:120]))
except Exception as e:
    print("Could not list attrs:", e)

# Try a set of common read/account methods and print raw outputs
methods_to_try = [
    ("get_accounts", {}),
    ("list_accounts", {}),
    ("get_all_accounts", {}),
    ("accounts", {}),
    ("get_account", {"account_id": None}),  # will fail unless account id provided
    ("get_balances", {}),
    ("get_account_balance", {}),
    ("get_balances_for_currency", {"currency":"USD"}),
]

print("\n--- Trying common account methods ---")
for name, kwargs in methods_to_try:
    fn = getattr(client, name, None)
    if not callable(fn):
        print(f"{name}: NOT FOUND")
        continue
    print(f"\n{name} -> calling {name} with kwargs={kwargs} ...")
    try:
        # try calling with no args first (some accept none)
        try:
            out = fn()
        except TypeError:
            # attempt with kwargs if provided and method signature different
            try:
                out = fn(**{k:v for k,v in kwargs.items() if v is not None})
            except Exception as e:
                out = f"call failed: {e}"
        # pretty print type and repr/summary
        print("-> type:", type(out))
        if isinstance(out, dict):
            print("-> dict keys:", list(out.keys()))
            # print small sample
            try:
                print("-> preview:", json.dumps({k: out[k] for k in list(out)[:5]}, default=str, indent=2))
            except Exception:
                print("-> preview (repr):", repr(out)[:1000])
        elif isinstance(out, list):
            print("-> list length:", len(out))
            if len(out) > 0:
                print("-> first item type:", type(out[0]))
                try:
                    print("-> first item preview:", json.dumps(out[0], default=str, indent=2)[:1000])
                except Exception:
                    print("-> first item repr:", repr(out[0])[:1000])
        else:
            try:
                print("-> repr/out:", repr(out)[:2000])
            except Exception:
                print("-> output (non-serializable) - see below")
    except Exception as e:
        print("Exception when calling:", e)
        traceback.print_exc()

# Try spot price as a fallback to estimate conversions
print("\n--- Trying price/market helper methods ---")
price_methods = ["get_spot_price", "get_price", "get_ticker", "get_product_ticker", "ticker"]
for pm in price_methods:
    pf = getattr(client, pm, None)
    if not callable(pf):
        print(f"{pm}: NOT FOUND")
        continue
    try:
        product = "BTC-USD"
        try:
            out = pf(product_id=product)
        except TypeError:
            out = pf(product)
        print(f"{pm} -> type {type(out)}; preview: {repr(out)[:500]}")
    except Exception as e:
        print(f"{pm} call error:", e)

print("\n=== END DEBUG ===")
