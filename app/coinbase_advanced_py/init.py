# shim to alias coinbase_advanced_py as coinbase_advanced
try:
    from coinbase_advanced import *
except ImportError:
    from coinbase_advanced_py import *
