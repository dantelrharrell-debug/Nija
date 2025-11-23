# Shim for top-level import `import tradingview_webhook`
try:
    # If the actual code lives in web/tradingview_webhook.py and exposes `bp`
    from web.tradingview_webhook import bp as bp  # re-export blueprint 'bp'
    # Optionally export helpers used by main.py:
    # from web.tradingview_webhook import create_blueprint as create_blueprint
except Exception as e:
    # Raise a clear import error so logs show what's wrong
    raise ImportError("tradingview_webhook shim: failed to import web.tradingview_webhook: " + repr(e))
