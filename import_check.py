import sys, importlib, traceback
print("sys.path:", sys.path[:6])

def try_import(name):
    print("=== import", name)
    try:
        m = importlib.import_module(name)
        print("OK:", name, "->", getattr(m, "__file__", None))
    except Exception:
        traceback.print_exc()

try_import("coinbase_adapter")
try_import("tradingview_webhook")
try_import("web.tradingview_webhook")
