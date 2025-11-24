# Shim for top-level import `import tradingview_webhook`
# Re-export the canonical blueprint from src.trading.tradingview_webhook
# This prevents ImportError and circular import scenarios.

try:
    # Primary: import from src.trading.tradingview_webhook (canonical location)
    from src.trading.tradingview_webhook import bp, tradingview_blueprint
except ImportError:
    try:
        # Fallback: import from web.tradingview_webhook if src.trading doesn't exist
        from web.tradingview_webhook import bp
        tradingview_blueprint = bp
    except Exception as e:
        # Raise a clear import error so logs show what's wrong
        raise ImportError("tradingview_webhook shim: failed to import from src.trading or web: " + repr(e))
