# Thin wrapper so code using `import coinbase_advanced` works
# It re-exports everything from the vendored implementation.

from importlib import util, import_module
import pkgutil
import os
import sys

# compute path to the vendored implementation
HERE = os.path.dirname(__file__)
VENDORED_IMPL = os.path.normpath(os.path.join(HERE, "..", "coinbase_advanced_py"))

# Insert vendored implementation into sys.path so it can be imported
if VENDORED_IMPL not in sys.path:
    sys.path.insert(0, VENDORED_IMPL)

# try to import the main module from vendored implementation
try:
    _impl = import_module("client") if pkgutil.find_loader("client") else import_module("coinbase_advanced_py.client")
except Exception:
    # fallback: import the vendored package as a package
    try:
        _impl = import_module("coinbase_advanced_py")
    except Exception:
        _impl = None

# Expose names from the vendored module if available
if _impl:
    # import all public names
    for attr in dir(_impl):
        if not attr.startswith("_"):
            globals()[attr] = getattr(_impl, attr)
