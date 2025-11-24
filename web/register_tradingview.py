from flask import Blueprint
import importlib
import logging
import traceback

logger = logging.getLogger(__name__)

def try_register_tradingview(app):
    """
    Attempt to import and register a TradingView blueprint from several candidate
    modules/attributes. Returns the blueprint name on success, or None on failure.
    """
    candidates = [
        ("src.trading.tradingview_webhook", "tradingview_blueprint"),
        ("web.tradingview_webhook", "bp"),
        ("tradingview_webhook", "bp"),
        ("tradingview_webhook", "tradingview_blueprint"),
    ]

    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
            if not hasattr(mod, attr):
                logger.debug("Module %s has no attribute %s", mod_name, attr)
                continue
            bp = getattr(mod, attr)
            if not isinstance(bp, Blueprint):
                logger.debug("Attribute %s.%s is not a Flask Blueprint (type=%s)", mod_name, attr, type(bp))
                continue

            if bp.name in app.blueprints:
                logger.info("TradingView blueprint already registered (name=%s), skipping", bp.name)
                return bp.name

            try:
                app.register_blueprint(bp, url_prefix="/tv")
                logger.info("✅ TradingView blueprint registered at /tv (from %s.%s)", mod_name, attr)
                return bp.name
            except Exception as reg_exc:
                logger.warning(
                    "Failed to register blueprint %s from %s: %s\n%s",
                    attr, mod_name, reg_exc, traceback.format_exc()
                )
                continue

        except Exception as imp_exc:
            logger.debug(
                "TradingView import attempt %s.%s failed: %s\n%s",
                mod_name, attr, imp_exc, traceback.format_exc()
            )
            continue

    logger.warning("⚠️ TradingView blueprint not found; skipping registration")
    return None
