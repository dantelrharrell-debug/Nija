# shim to map whatever upstream provides to the expected import name
try:
    # try the expected module first
    from coinbase_advanced import *
except Exception:
    # fallback to the alternate name some builds use
    from coinbase_advanced_py import *
