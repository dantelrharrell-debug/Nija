# Shim for top-level import `import tradingview_webhook`
# Re-exports the canonical blueprint from src.trading.tradingview_webhook,
# with fallback to web.tradingview_webhook for compatibility.

import logging

_logger = logging.getLogger(__name__)

# Try canonical location first
try:
    from src.trading.tradingview_webhook import tradingview_blueprint as bp
    from src.trading.tradingview_webhook import tradingview_blueprint
    _logger.debug("Loaded tradingview_blueprint from src.trading.tradingview_webhook")
except ImportError as e:
    _logger.warning(
        "Could not import from src.trading.tradingview_webhook (%s), "
        "falling back to web.tradingview_webhook", e
    )
    try:
        from web.tradingview_webhook import bp as bp
        tradingview_blueprint = bp
    except ImportError as e2:
        raise ImportError(
            "tradingview_webhook shim: failed to import from both "
            "src.trading.tradingview_webhook and web.tradingview_webhook: "
            + repr(e2)
        ) from e2
