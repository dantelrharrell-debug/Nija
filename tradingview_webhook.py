# Shim to preserve legacy top-level import name.
# If the real module lives in web/tradingview_webhook.py, import and re-export it here.

try:
    from web.tradingview_webhook import bp as bp  # blueprint name used by main.py (adjust if needed)
    from web.tradingview_webhook import create_blueprint as create_blueprint  # optional
except Exception:
    # Fallback: try importing top-level tradingview_webhook (if it already exists)
    try:
        from tradingview_webhook import bp as bp  # noqa: F401
    except Exception:
        # Re-raise with clear message for logs
        raise ImportError("tradingview_webhook shim: failed to import web.tradingview_webhook; ensure the real module exists at web/tradingview_webhook.py")
