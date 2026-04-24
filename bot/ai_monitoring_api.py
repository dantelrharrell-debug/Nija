"""
NIJA AI Monitoring API
========================

Flask Blueprint exposing real-time AI/system status endpoints:

    GET /ai/regime              — current market regime snapshot
    GET /ai/trade-confidence    — trade confidence score for a symbol+side
    GET /ai/liquidity-map       — order-book liquidity heatmap for a symbol
    GET /system/brain-status    — overall AI brain health dashboard
    GET /system/execution-expectancy — expectancy kill-switch cooldown status
    GET /system/ecel-status     — ECEL compiler/schema health status

Query Parameters
----------------
All ``/ai/*`` endpoints accept:

``symbol``   Trading pair (default: ``"BTC-USD"``)

``/ai/trade-confidence`` additionally accepts:

``side``     ``"long"`` or ``"short"`` (default: ``"long"``)

``/ai/liquidity-map`` additionally accepts:

``bid``      Best bid price (float)
``ask``      Best ask price (float)
``size``     Proposed order size in USD (default: 0)

Integration
-----------
Register in your Flask app or dashboard_server.py::

    from bot.ai_monitoring_api import ai_monitoring_bp, register_ai_monitoring
    register_ai_monitoring(app)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any

from flask import Blueprint, Flask, jsonify, request, current_app

logger = logging.getLogger("nija.ai_monitoring_api")

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

ai_monitoring_bp = Blueprint("ai_monitoring", __name__)


# ---------------------------------------------------------------------------
# Lazy singleton accessors (imported at request-time to avoid circular issues)
# ---------------------------------------------------------------------------

def _get_regime_engine():
    try:
        from bot.market_regime_detector import get_market_regime_detector
        return get_market_regime_detector()
    except ImportError:
        from market_regime_detector import get_market_regime_detector
        return get_market_regime_detector()


def _get_confidence_engine():
    try:
        from bot.ai_trade_confidence_engine import get_ai_trade_confidence_engine
        return get_ai_trade_confidence_engine()
    except ImportError:
        from ai_trade_confidence_engine import get_ai_trade_confidence_engine
        return get_ai_trade_confidence_engine()


def _get_heatmap_analyzer():
    try:
        from bot.liquidity_heatmap_analyzer import get_liquidity_heatmap_analyzer
        return get_liquidity_heatmap_analyzer()
    except ImportError:
        from liquidity_heatmap_analyzer import get_liquidity_heatmap_analyzer
        return get_liquidity_heatmap_analyzer()


def _get_execution_engine_from_context():
    """Resolve the active execution engine from app context without creating one."""
    app = current_app

    # Direct injection preferred
    direct = app.config.get("EXECUTION_ENGINE") or app.config.get("execution_engine")
    if direct is not None:
        return direct

    # Strategy-level injection fallback
    strategy = (
        app.config.get("TRADING_STRATEGY")
        or app.config.get("APEX_STRATEGY")
        or app.config.get("strategy")
    )
    if strategy is not None and hasattr(strategy, "execution_engine"):
        return getattr(strategy, "execution_engine")

    return None


def _get_execution_pipeline_from_context():
    """Resolve the active execution pipeline from context or singleton."""
    app = current_app

    direct = app.config.get("EXECUTION_PIPELINE") or app.config.get("execution_pipeline")
    if direct is not None:
        return direct

    exec_engine = _get_execution_engine_from_context()
    if exec_engine is not None and hasattr(exec_engine, "execution_pipeline"):
        return getattr(exec_engine, "execution_pipeline")

    strategy = (
        app.config.get("TRADING_STRATEGY")
        or app.config.get("APEX_STRATEGY")
        or app.config.get("strategy")
    )
    if strategy is not None and hasattr(strategy, "execution_pipeline"):
        return getattr(strategy, "execution_pipeline")

    # Final fallback: process-wide singleton.
    try:
        from bot.execution_pipeline import get_execution_pipeline
    except ImportError:
        try:
            from execution_pipeline import get_execution_pipeline
        except ImportError:
            return None

    try:
        return get_execution_pipeline()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------

def _ok(data: Dict[str, Any], status: int = 200):
    return jsonify({"success": True, "data": data, "timestamp": datetime.now().isoformat()}), status


def _err(message: str, status: int = 500):
    return jsonify({"success": False, "error": message, "timestamp": datetime.now().isoformat()}), status


# ---------------------------------------------------------------------------
# /ai/regime
# ---------------------------------------------------------------------------

@ai_monitoring_bp.route("/ai/regime", methods=["GET"])
def ai_regime():
    """
    Return the current market regime snapshot.

    Query params
    ------------
    symbol : str
        Trading pair used as label in the response (default: ``"BTC-USD"``).
        Pass ``refresh=1`` to force a re-classify using a synthetic minimal
        DataFrame (useful for smoke-testing without a live feed).
    """
    symbol = request.args.get("symbol", "BTC-USD")

    try:
        engine = _get_regime_engine()
        current = engine.get_current()

        if current is None:
            # No detection has been run yet — return the config summary
            return _ok({
                "symbol": symbol,
                "regime": "unknown",
                "message": (
                    "No regime classification available yet. "
                    "The engine runs its first classification when detect() is "
                    "called from the trading strategy loop."
                ),
                "history_length": 0,
            })

        data = engine.regime_summary()
        data["symbol"] = symbol
        data["history_length"] = len(engine.get_history(200))
        return _ok(data)

    except Exception as exc:
        logger.exception("Error in /ai/regime")
        return _err(str(exc))


# ---------------------------------------------------------------------------
# /ai/trade-confidence
# ---------------------------------------------------------------------------

@ai_monitoring_bp.route("/ai/trade-confidence", methods=["GET"])
def ai_trade_confidence():
    """
    Return a trade confidence score for *symbol* / *side*.

    This endpoint runs a lightweight evaluation against the most recently
    available regime snapshot and a stub indicator set derived from query
    parameters.  For accurate live scores the trading loop calls the engine
    directly with real OHLCV data.

    Query params
    ------------
    symbol : str
        e.g. ``BTC-USD`` (default).
    side : str
        ``"long"`` or ``"short"`` (default: ``"long"``).
    adx : float
        ADX value (default: 20).
    rsi : float
        RSI-14 value (default: 50).
    rsi9 : float
        RSI-9 value (default: 50).
    atr_pct : float
        ATR as percentage of price, e.g. 0.015 for 1.5 % (default: 0.015).
    """
    import pandas as pd
    import numpy as np

    symbol = request.args.get("symbol", "BTC-USD")
    side = request.args.get("side", "long").lower()

    # Build a minimal synthetic indicator dict from query params
    adx_val = float(request.args.get("adx", 20))
    rsi_val = float(request.args.get("rsi", 50))
    rsi9_val = float(request.args.get("rsi9", rsi_val))
    atr_pct = float(request.args.get("atr_pct", 0.015))
    mid_price = float(request.args.get("price", 100.0))
    atr_val = mid_price * atr_pct

    # Synthetic OHLCV DataFrame (single row, neutral)
    n = 30
    prices = np.linspace(mid_price * 0.98, mid_price, n)
    vols = np.ones(n) * 1_000.0
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.001,
        "low": prices * 0.998,
        "close": prices,
        "volume": vols,
    })

    indicators = {
        "adx": pd.Series([adx_val] * n),
        "rsi_14": pd.Series([rsi_val] * n),
        "rsi_9": pd.Series([rsi9_val] * n),
        "atr": pd.Series([atr_val] * n),
        "macd_histogram": pd.Series([0.0] * n),
        "ema_9": pd.Series([mid_price] * n),
        "ema_21": pd.Series([mid_price * 0.999] * n),
        "ema_50": pd.Series([mid_price * 0.998] * n),
    }

    try:
        engine = _get_confidence_engine()
        result = engine.evaluate(df, indicators, side=side, symbol=symbol)
        return _ok(result)

    except Exception as exc:
        logger.exception("Error in /ai/trade-confidence")
        return _err(str(exc))


# ---------------------------------------------------------------------------
# /ai/liquidity-map
# ---------------------------------------------------------------------------

@ai_monitoring_bp.route("/ai/liquidity-map", methods=["GET"])
def ai_liquidity_map():
    """
    Return the liquidity heatmap for a symbol.

    Query params
    ------------
    symbol : str
        e.g. ``BTC-USD`` (default).
    bid : float
        Best bid price (required for meaningful output; default: 100.0).
    ask : float
        Best ask price (default: ``bid * 1.001``).
    size : float
        Proposed trade size in USD (default: 0).
    """
    symbol = request.args.get("symbol", "BTC-USD")
    bid = float(request.args.get("bid", 100.0))
    ask = float(request.args.get("ask", bid * 1.001))
    trade_size = float(request.args.get("size", 0.0))

    try:
        analyzer = _get_heatmap_analyzer()
        result = analyzer.analyze(
            symbol=symbol,
            bid=bid,
            ask=ask,
            trade_size_usd=trade_size,
        )
        return _ok(result)

    except Exception as exc:
        logger.exception("Error in /ai/liquidity-map")
        return _err(str(exc))


# ---------------------------------------------------------------------------
# /system/brain-status
# ---------------------------------------------------------------------------

@ai_monitoring_bp.route("/system/brain-status", methods=["GET"])
def system_brain_status():
    """
    Return a unified status dashboard for all AI brain components.

    Reports availability and last-known state of:
    - Market Regime Detection Engine
    - AI Trade Confidence Engine
    - Liquidity Heatmap Analyzer
    - Global Risk Controller
    - AI Intelligence Hub (if available)
    """
    status: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "overall_health": "healthy",
        "components": {},
    }
    issues = []

    # --- Market Regime Detection Engine ---
    try:
        engine = _get_regime_engine()
        current = engine.get_current()
        status["components"]["market_regime_detector"] = {
            "status": "online",
            "current_regime": current.regime.value if current else "not_yet_classified",
            "confidence": round(current.confidence, 4) if current else 0.0,
            "history_length": len(engine.get_history(200)),
            "bars_in_regime": engine._bars_in_regime,
        }
    except Exception as exc:
        status["components"]["market_regime_detector"] = {
            "status": "error",
            "error": str(exc),
        }
        issues.append("market_regime_detector")

    # --- AI Trade Confidence Engine ---
    try:
        conf_engine = _get_confidence_engine()
        status["components"]["ai_trade_confidence_engine"] = {
            "status": "online",
            "threshold": conf_engine.confidence_threshold,
            "regime_detector_linked": conf_engine._regime_engine is not None,
        }
    except Exception as exc:
        status["components"]["ai_trade_confidence_engine"] = {
            "status": "error",
            "error": str(exc),
        }
        issues.append("ai_trade_confidence_engine")

    # --- Liquidity Heatmap Analyzer ---
    try:
        heatmap = _get_heatmap_analyzer()
        status["components"]["liquidity_heatmap_analyzer"] = {
            "status": "online",
            "depth_band_pct": heatmap.depth_band_pct,
            "bucket_count": heatmap.bucket_count,
            "min_depth_usd": heatmap.min_depth_usd,
        }
    except Exception as exc:
        status["components"]["liquidity_heatmap_analyzer"] = {
            "status": "error",
            "error": str(exc),
        }
        issues.append("liquidity_heatmap_analyzer")

    # --- Global Risk Controller ---
    try:
        try:
            from bot.global_risk_controller import get_global_risk_controller
        except ImportError:
            from global_risk_controller import get_global_risk_controller
        grc = get_global_risk_controller()
        allowed, reason = grc.is_trading_allowed()
        status["components"]["global_risk_controller"] = {
            "status": "online",
            "trading_allowed": allowed,
            "risk_level": getattr(grc, "_risk_level", "unknown"),
            "reason": reason if not allowed else "ok",
        }
    except Exception as exc:
        status["components"]["global_risk_controller"] = {
            "status": "unavailable",
            "note": str(exc),
        }

    # --- AI Intelligence Hub ---
    try:
        try:
            from bot.ai_intelligence_hub import get_ai_intelligence_hub
        except ImportError:
            from ai_intelligence_hub import get_ai_intelligence_hub
        hub = get_ai_intelligence_hub()
        status["components"]["ai_intelligence_hub"] = {
            "status": "online",
            "regime_ai": getattr(hub, "REGIME_AI_AVAILABLE", False),
            "portfolio_risk": getattr(hub, "PORTFOLIO_RISK_AVAILABLE", False),
            "capital_brain": getattr(hub, "CAPITAL_BRAIN_AVAILABLE", False),
        }
    except Exception as exc:
        status["components"]["ai_intelligence_hub"] = {
            "status": "unavailable",
            "note": str(exc),
        }

    # --- Execution Engine Expectancy Kill-Switch ---
    try:
        exec_engine = _get_execution_engine_from_context()
        if exec_engine is not None and hasattr(exec_engine, "get_expectancy_kill_switch_status"):
            ks = exec_engine.get_expectancy_kill_switch_status()
            status["components"]["execution_expectancy_kill_switch"] = {
                "status": "online",
                "disabled_total": ks.get("disabled_total", 0),
                "auto_cooldown_active": ks.get("auto_cooldown_active", 0),
                "manual_or_legacy_active": ks.get("manual_or_legacy_active", 0),
                "force_enable_buckets": ks.get("force_enable_buckets", []),
                "active_buckets": ks.get("active_buckets", []),
            }
        else:
            status["components"]["execution_expectancy_kill_switch"] = {
                "status": "unavailable",
                "note": "execution engine not attached to monitoring app context",
            }
    except Exception as exc:
        status["components"]["execution_expectancy_kill_switch"] = {
            "status": "error",
            "error": str(exc),
        }
        issues.append("execution_expectancy_kill_switch")

    # --- ECEL Compiler / Schema Health ---
    try:
        pipeline = _get_execution_pipeline_from_context()
        if pipeline is not None and hasattr(pipeline, "get_status"):
            pstatus = pipeline.get_status()
            ecel = pstatus.get("ecel", {}) if isinstance(pstatus, dict) else {}

            if ecel.get("enabled"):
                status["components"]["ecel_execution_compiler"] = {
                    "status": "online",
                    "coinbase_rules": ecel.get("coinbase_rules", 0),
                    "kraken_rules": ecel.get("kraken_rules", 0),
                    "background_refresh_thread_alive": ecel.get("background_refresh_thread_alive", False),
                    "refresh_health": ecel.get("refresh_health", {}),
                }
            else:
                status["components"]["ecel_execution_compiler"] = {
                    "status": "unavailable",
                    "note": "execution pipeline present but ECEL not enabled",
                }
        else:
            status["components"]["ecel_execution_compiler"] = {
                "status": "unavailable",
                "note": "execution pipeline not attached to monitoring app context",
            }
    except Exception as exc:
        status["components"]["ecel_execution_compiler"] = {
            "status": "error",
            "error": str(exc),
        }
        issues.append("ecel_execution_compiler")

    # Overall health
    if len(issues) >= 2:
        status["overall_health"] = "degraded"
    elif issues:
        status["overall_health"] = "partial"

    status["issues"] = issues
    return _ok(status)


@ai_monitoring_bp.route("/system/execution-expectancy", methods=["GET"])
def execution_expectancy_status():
    """Return detailed execution expectancy kill-switch state."""
    try:
        exec_engine = _get_execution_engine_from_context()
        if exec_engine is None or not hasattr(exec_engine, "get_expectancy_kill_switch_status"):
            return _err("Execution engine not attached to monitoring app context", status=503)

        max_rows = int(request.args.get("max_rows", 25))
        return _ok(exec_engine.get_expectancy_kill_switch_status(max_rows=max_rows))
    except Exception as exc:
        logger.exception("Error in /system/execution-expectancy")
        return _err(str(exc))


@ai_monitoring_bp.route("/system/ecel-status", methods=["GET"])
def ecel_status():
    """Return detailed ECEL compiler and schema refresh status."""
    try:
        pipeline = _get_execution_pipeline_from_context()
        if pipeline is None or not hasattr(pipeline, "get_status"):
            return _err("Execution pipeline not attached to monitoring app context", status=503)

        pstatus = pipeline.get_status()
        if not isinstance(pstatus, dict):
            return _err("Execution pipeline status unavailable", status=503)

        ecel = pstatus.get("ecel", {})
        if not ecel or not ecel.get("enabled"):
            return _err("ECEL is not enabled in execution pipeline", status=503)

        return _ok(ecel)
    except Exception as exc:
        logger.exception("Error in /system/ecel-status")
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_ai_monitoring(app: Flask, execution_engine=None, strategy=None, execution_pipeline=None) -> None:
    """
    Register the AI monitoring blueprint on an existing Flask *app*.

    The blueprint mounts directly at the root (no URL prefix) so endpoints
    are accessible as ``/ai/regime``, ``/ai/trade-confidence``, etc.

    Parameters
    ----------
    app:
        The Flask application instance.
    execution_engine:
        Optional live execution engine instance to expose diagnostics for.
    strategy:
        Optional strategy instance that owns ``strategy.execution_engine``.
    execution_pipeline:
        Optional execution pipeline instance to expose ECEL diagnostics for.
    """
    if execution_engine is not None:
        app.config["EXECUTION_ENGINE"] = execution_engine
    if strategy is not None:
        app.config["TRADING_STRATEGY"] = strategy
    if execution_pipeline is not None:
        app.config["EXECUTION_PIPELINE"] = execution_pipeline

    app.register_blueprint(ai_monitoring_bp)
    logger.info(
        "AI Monitoring API registered: "
        "/ai/regime, /ai/trade-confidence, /ai/liquidity-map, "
        "/system/brain-status, /system/execution-expectancy, /system/ecel-status"
    )
