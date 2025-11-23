# Shim for top-level import `import tradingview_webhook`
# Re-exports the real blueprint from web/tradingview_webhook.py if present,
# otherwise raises a clear ImportError for logs.

try:
    # Adjust the names below if your blueprint/object names differ.
    from web.tradingview_webhook import bp as bp  # blueprint object expected by main.py
    # Optionally re-export helper functions or factory names used by main.py
    # from web.tradingview_webhook import create_blueprint as create_blueprint
except Exception as _e:
    # Give a clear, actionable message that will appear in logs.
    raise ImportError(
        "tradingview_webhook shim: failed to import web.tradingview_webhook. "
        "Ensure the file web/tradingview_webhook.py exists and exports 'bp' "
        "(or update main.py to import the correct module path). Original error: "
        + repr(_e)
    )
