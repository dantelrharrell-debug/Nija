# tradingview_webhook.py (repo root) - shim that re-exports the canonical blueprint
try:
    # Prefer the src-based canonical module if available
    from src.trading.tradingview_webhook import bp as bp, tradingview_blueprint as tradingview_blueprint
except Exception:
    # Fallback to web module if src import not present
    try:
        from web.tradingview_webhook import bp as bp, tradingview_blueprint as tradingview_blueprint
    except Exception as e:
        # Raise a clear ImportError to be handled by the app startup code
        raise ImportError("tradingview_webhook shim: failed to import tradingview blueprint: " + repr(e))
