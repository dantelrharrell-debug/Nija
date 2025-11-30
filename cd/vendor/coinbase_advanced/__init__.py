# cd/vendor/coinbase_advanced/__init__.py
# small shim so code that does `import coinbase_advanced` can find the vendored package
# Assumes cd/vendor is on PYTHONPATH (we add it in entrypoint)
try:
    # prefer the vendored coinbase_advanced_py package
    from coinbase_advanced_py import *  # re-export everything
    # optional: expose client directly for convenience
    try:
        from coinbase_advanced_py.client import Client  # noqa: F401
    except Exception:
        pass
except Exception:
    # If this fails it's okay — import errors will show in logs
    raise
