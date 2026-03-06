"""
NIJA Enhanced Performance Dashboard
=====================================

Provides real-time performance, risk, and strategy-intelligence endpoints that
complement the existing ``PerformanceDashboard`` and ``dashboard_server`` with
three focused view areas:

1. **Risk Engine view** — live capital-protection status, drawdown, exposure,
   and risk-level from ``RiskEngine``.

2. **Strategy Intelligence view** — current market regime, active strategies,
   and AI signal quality from ``StrategyIntelligenceLayer``.

3. **KPI / P&L view** — portfolio-wide win rate, Sharpe ratio, daily/weekly
   P&L summary, and top-performing symbols from ``PerformanceDashboard`` and
   ``PerformanceMetricsCalculator``.

Flask integration
-----------------
Register the blueprint on your existing Flask app::

    from bot.performance_dashboard_enhanced import create_enhanced_dashboard_blueprint

    app = Flask(__name__)
    app.register_blueprint(create_enhanced_dashboard_blueprint())

Endpoints added
---------------
* ``GET /api/performance/risk``         — risk-engine status snapshot
* ``GET /api/performance/strategy``     — strategy-intelligence status snapshot
* ``GET /api/performance/kpi``          — top-level KPI summary
* ``GET /api/performance/full``         — all three sections combined
* ``GET /performance``                  — human-readable HTML dashboard page

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, jsonify

logger = logging.getLogger("nija.performance_dashboard_enhanced")

# ---------------------------------------------------------------------------
# Optional subsystem imports
# ---------------------------------------------------------------------------

try:
    from risk_engine import get_risk_engine
    _RISK_ENGINE_AVAILABLE = True
except ImportError:
    try:
        from bot.risk_engine import get_risk_engine
        _RISK_ENGINE_AVAILABLE = True
    except ImportError:
        _RISK_ENGINE_AVAILABLE = False
        get_risk_engine = None  # type: ignore
        logger.warning("RiskEngine not available — /api/performance/risk will return stub")

try:
    from strategy_intelligence_layer import (
        get_strategy_intelligence_layer,
        _HUB_AVAILABLE,
        _SDE_AVAILABLE,
        _RANKER_AVAILABLE,
    )
    _SIL_AVAILABLE = True
except ImportError:
    try:
        from bot.strategy_intelligence_layer import (
            get_strategy_intelligence_layer,
            _HUB_AVAILABLE,
            _SDE_AVAILABLE,
            _RANKER_AVAILABLE,
        )
        _SIL_AVAILABLE = True
    except ImportError:
        _SIL_AVAILABLE = False
        get_strategy_intelligence_layer = None  # type: ignore
        _HUB_AVAILABLE = False
        _SDE_AVAILABLE = False
        _RANKER_AVAILABLE = False
        logger.warning("StrategyIntelligenceLayer not available — /api/performance/strategy will return stub")

try:
    from performance_metrics import get_performance_calculator
    _PERF_METRICS_AVAILABLE = True
except ImportError:
    try:
        from bot.performance_metrics import get_performance_calculator
        _PERF_METRICS_AVAILABLE = True
    except ImportError:
        _PERF_METRICS_AVAILABLE = False
        get_performance_calculator = None  # type: ignore
        logger.warning("PerformanceMetricsCalculator not available — KPI metrics will be limited")

try:
    from performance_dashboard import PerformanceDashboard
    _PERF_DASHBOARD_AVAILABLE = True
except ImportError:
    try:
        from bot.performance_dashboard import PerformanceDashboard
        _PERF_DASHBOARD_AVAILABLE = True
    except ImportError:
        _PERF_DASHBOARD_AVAILABLE = False
        PerformanceDashboard = None  # type: ignore
        logger.warning("PerformanceDashboard not available — portfolio summary will be limited")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _safe_get_risk_status() -> Dict[str, Any]:
    """Return the RiskEngine status dict or a safe stub on error."""
    if not _RISK_ENGINE_AVAILABLE:
        return {"available": False, "reason": "RiskEngine module not loaded"}
    try:
        engine = get_risk_engine()
        status = engine.get_status()
        status["available"] = True
        return status
    except Exception as exc:
        logger.debug("RiskEngine.get_status error: %s", exc)
        return {"available": False, "reason": str(exc)}


def _safe_get_strategy_status() -> Dict[str, Any]:
    """Return the StrategyIntelligenceLayer status dict or a safe stub."""
    if not _SIL_AVAILABLE:
        return {"available": False, "reason": "StrategyIntelligenceLayer module not loaded"}
    try:
        layer = get_strategy_intelligence_layer()
        status = layer.get_status()
        status["available"] = True
        return status
    except Exception as exc:
        logger.debug("StrategyIntelligenceLayer.get_status error: %s", exc)
        return {"available": False, "reason": str(exc)}


def _safe_get_kpi_summary() -> Dict[str, Any]:
    """Return a top-level KPI summary merging PerformanceDashboard and metrics."""
    result: Dict[str, Any] = {
        "available": False,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Portfolio summary from the existing PerformanceDashboard
    if _PERF_DASHBOARD_AVAILABLE:
        try:
            dash = PerformanceDashboard()
            summary = dash.get_portfolio_summary()
            result["portfolio_summary"] = summary
            result["available"] = True
        except Exception as exc:
            logger.debug("PerformanceDashboard.get_portfolio_summary error: %s", exc)
            result["portfolio_summary"] = {"error": str(exc)}

    # Detailed metrics from PerformanceMetricsCalculator
    if _PERF_METRICS_AVAILABLE:
        try:
            calc = get_performance_calculator()
            snapshot = calc.get_current_snapshot() if hasattr(calc, "get_current_snapshot") else {}
            result["metrics_snapshot"] = snapshot if isinstance(snapshot, dict) else {}
            result["available"] = True
        except Exception as exc:
            logger.debug("PerformanceMetricsCalculator error: %s", exc)
            result["metrics_snapshot"] = {"error": str(exc)}

    if not result["available"]:
        result["reason"] = "No performance subsystems loaded"

    return result


# ---------------------------------------------------------------------------
# Blueprint factory
# ---------------------------------------------------------------------------

def create_enhanced_dashboard_blueprint(url_prefix: str = "") -> Blueprint:
    """
    Create and return the enhanced-performance Flask blueprint.

    Parameters
    ----------
    url_prefix:
        Optional URL prefix for all routes (default ``""`` — no prefix).

    Returns
    -------
    flask.Blueprint
    """
    bp = Blueprint("enhanced_dashboard", __name__, url_prefix=url_prefix)

    # ── /api/performance/risk ──────────────────────────────────────────
    @bp.route("/api/performance/risk", methods=["GET"])
    def api_performance_risk():
        """Live capital-protection status from the Risk Engine."""
        return jsonify({
            "section": "risk_engine",
            "timestamp": datetime.utcnow().isoformat(),
            "data": _safe_get_risk_status(),
        })

    # ── /api/performance/strategy ──────────────────────────────────────
    @bp.route("/api/performance/strategy", methods=["GET"])
    def api_performance_strategy():
        """Current strategy-intelligence layer status."""
        return jsonify({
            "section": "strategy_intelligence",
            "timestamp": datetime.utcnow().isoformat(),
            "data": _safe_get_strategy_status(),
        })

    # ── /api/performance/kpi ───────────────────────────────────────────
    @bp.route("/api/performance/kpi", methods=["GET"])
    def api_performance_kpi():
        """Portfolio-wide KPI summary (win rate, P&L, Sharpe ratio, etc.)."""
        return jsonify({
            "section": "kpi",
            "timestamp": datetime.utcnow().isoformat(),
            "data": _safe_get_kpi_summary(),
        })

    # ── /api/performance/full ──────────────────────────────────────────
    @bp.route("/api/performance/full", methods=["GET"])
    def api_performance_full():
        """Combined risk + strategy + KPI snapshot in a single response."""
        return jsonify({
            "section": "full",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "risk_engine": _safe_get_risk_status(),
                "strategy_intelligence": _safe_get_strategy_status(),
                "kpi": _safe_get_kpi_summary(),
            },
        })

    # ── /performance (HTML page) ───────────────────────────────────────
    @bp.route("/performance", methods=["GET"])
    def performance_page():
        """Human-readable HTML performance dashboard."""
        from flask import make_response

        risk = _safe_get_risk_status()
        strategy = _safe_get_strategy_status()
        kpi = _safe_get_kpi_summary()

        risk_level = (
            risk.get("subsystems", {})
            .get("global_risk_controller", {})
            .get("risk_level", risk.get("capital", {}).get("current_balance_usd", "N/A"))
        )
        # Simplify: pull risk level string from GRC status
        grc = risk.get("subsystems", {}).get("global_risk_controller", {})
        risk_level_str = grc.get("level", "UNKNOWN") if isinstance(grc, dict) else "UNKNOWN"

        capital = risk.get("capital", {})
        balance = capital.get("current_balance_usd", 0.0)
        drawdown = capital.get("drawdown_pct", 0.0)
        exposure = capital.get("total_exposure_usd", 0.0)

        sil_cfg = strategy.get("config", {})
        regime = (
            strategy.get("subsystems", {})
            .get("ai_intelligence_hub_status", {})
            .get("regime", "UNKNOWN")
        )
        score_threshold = sil_cfg.get("ai_score_threshold", 75)

        port = kpi.get("portfolio_summary", {})
        total_trades = port.get("total_trades", "N/A")
        win_rate = port.get("win_rate", "N/A")
        total_pnl = port.get("total_pnl_usd", "N/A")

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="refresh" content="15"/>
  <title>NIJA Performance Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;padding:24px}}
    h1{{font-size:1.6rem;font-weight:700;margin-bottom:4px;color:#58a6ff}}
    .subtitle{{color:#8b949e;font-size:.85rem;margin-bottom:24px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px}}
    .card h2{{font-size:1rem;font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}}
    .badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600}}
    .green{{background:#1a4731;color:#3fb950}}
    .yellow{{background:#3d2f00;color:#d29922}}
    .red{{background:#3c1010;color:#f85149}}
    .row{{display:flex;justify-content:space-between;align-items:center;
          padding:6px 0;border-bottom:1px solid #21262d;font-size:.85rem}}
    .row:last-child{{border-bottom:none}}
    .label{{color:#8b949e}}
    .value{{font-weight:600}}
    .footer{{margin-top:24px;text-align:center;color:#8b949e;font-size:.78rem}}
    .api-links a{{color:#58a6ff;text-decoration:none;margin:0 8px}}
    .api-links a:hover{{text-decoration:underline}}
  </style>
</head>
<body>
  <h1>⚡ NIJA Performance Dashboard</h1>
  <p class="subtitle">Live capital-protection · strategy intelligence · KPI metrics &nbsp;|&nbsp; {now}</p>

  <div class="grid">

    <!-- Risk Engine card -->
    <div class="card">
      <h2>🛡️ Risk Engine
        <span class="badge {'green' if risk_level_str in ('GREEN','UNKNOWN') else 'yellow' if risk_level_str=='YELLOW' else 'red'}">{risk_level_str}</span>
      </h2>
      <div class="row"><span class="label">Balance</span>
        <span class="value">${balance:,.2f}</span></div>
      <div class="row"><span class="label">Drawdown</span>
        <span class="value {'red' if float(drawdown or 0)>10 else 'value'}">{drawdown:.2f}%</span></div>
      <div class="row"><span class="label">Total Exposure</span>
        <span class="value">${exposure:,.2f}</span></div>
      <div class="row"><span class="label">Capital Floor</span>
        <span class="value">${capital.get('floor_usd', 'N/A')}</span></div>
      <div class="row"><span class="label">Peak Balance</span>
        <span class="value">${capital.get('peak_balance_usd', 0):,.2f}</span></div>
    </div>

    <!-- Strategy Intelligence card -->
    <div class="card">
      <h2>🧠 Strategy Intelligence</h2>
      <div class="row"><span class="label">Market Regime</span>
        <span class="value">{regime}</span></div>
      <div class="row"><span class="label">Score Threshold</span>
        <span class="value">{score_threshold}/100</span></div>
      <div class="row"><span class="label">AI Hub</span>
        <span class="badge {'green' if _HUB_AVAILABLE else 'red'}">{'ON' if _HUB_AVAILABLE else 'OFF'}</span></div>
      <div class="row"><span class="label">Diversification Engine</span>
        <span class="badge {'green' if _SDE_AVAILABLE else 'red'}">{'ON' if _SDE_AVAILABLE else 'OFF'}</span></div>
      <div class="row"><span class="label">Trade Ranker</span>
        <span class="badge {'green' if _RANKER_AVAILABLE else 'red'}">{'ON' if _RANKER_AVAILABLE else 'OFF'}</span></div>
    </div>

    <!-- KPI card -->
    <div class="card">
      <h2>📊 Performance KPIs</h2>
      <div class="row"><span class="label">Total Trades</span>
        <span class="value">{total_trades}</span></div>
      <div class="row"><span class="label">Win Rate</span>
        <span class="value">{f'{float(win_rate)*100:.1f}%' if isinstance(win_rate, (int,float)) else win_rate}</span></div>
      <div class="row"><span class="label">Total P&amp;L</span>
        <span class="value">{f'${float(total_pnl):+,.2f}' if isinstance(total_pnl, (int,float)) else total_pnl}</span></div>
      <div class="row"><span class="label">Dashboard</span>
        <span class="badge green">LIVE</span></div>
    </div>

  </div>

  <div class="footer" style="margin-top:16px">
    <div class="api-links">
      <strong>JSON APIs:</strong>
      <a href="/api/performance/risk">/api/performance/risk</a>
      <a href="/api/performance/strategy">/api/performance/strategy</a>
      <a href="/api/performance/kpi">/api/performance/kpi</a>
      <a href="/api/performance/full">/api/performance/full</a>
    </div>
    <p style="margin-top:8px">Auto-refreshes every 15 s &nbsp;|&nbsp; NIJA Trading Systems</p>
  </div>
</body>
</html>"""

        resp = make_response(html, 200)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    return bp


__all__ = [
    "create_enhanced_dashboard_blueprint",
]
