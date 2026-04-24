"""
NIJA Global Risk Engine — Bot Package Entry Point
==================================================

Provides bot-package access to the GlobalRiskEngine defined in
``core/global_risk_engine.py``.

The GlobalRiskEngine is a centralised, multi-account risk aggregation layer
that sits above individual trade-level guards (GlobalRiskController,
GlobalRiskGovernor) and monitors the *entire portfolio* in real time.

Architecture context
--------------------
::

  ┌──────────────────────────────────────────────────────────┐
  │                   GlobalRiskEngine                        │
  │           (bot.global_risk_engine — this module)          │
  │                                                           │
  │  • Multi-account risk aggregation                         │
  │  • Portfolio-level exposure monitoring                    │
  │  • Global position limit enforcement                      │
  │  • Risk event logging with alert callbacks                │
  │  • Real-time drawdown and daily-loss tracking             │
  │  • Correlation/concentration risk assessment              │
  │                                                           │
  │  Complements (does NOT replace):                          │
  │    – GlobalRiskController  (kill-switch ladder)           │
  │    – GlobalRiskGovernor    (circuit-breaker gates)        │
  │    – RiskEngine            (per-trade sizing gate)        │
  └──────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.global_risk_engine import get_global_risk_engine

    engine = get_global_risk_engine()

    # Register per-account metrics each cycle:
    engine.update_account_metrics("account_1", {
        "current_balance": 10_000.0,
        "total_exposure": 3_500.0,
        "position_count": 4,
        "unrealized_pnl": 120.0,
    })

    # Aggregate portfolio view:
    portfolio = engine.calculate_portfolio_metrics()
    print(portfolio.total_exposure, portfolio.portfolio_drawdown_pct)

    # Guard before opening a new position:
    allowed, reason = engine.can_open_position("account_1", position_size=500.0)
    if not allowed:
        logger.warning("Position blocked: %s", reason)
        return

    # Register an alert callback:
    engine.register_alert_callback(lambda event: logger.warning(event.message))

    # Status dump for dashboards:
    print(engine.get_status_summary())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging

logger = logging.getLogger("nija.global_risk_engine")

# ---------------------------------------------------------------------------
# Import the canonical implementation from core/
# ---------------------------------------------------------------------------

try:
    from core.global_risk_engine import (
        GlobalRiskEngine,
        RiskLevel,
        RiskEventType,
        RiskEvent,
        AccountRiskMetrics,
        PortfolioRiskMetrics,
        get_global_risk_engine,
        reset_global_risk_engine,
    )
    _ENGINE_AVAILABLE = True
    logger.debug("GlobalRiskEngine loaded from core.global_risk_engine")
except ImportError:
    try:
        # Fallback: running directly from within the core/ directory
        from global_risk_engine import (  # type: ignore[no-redef]
            GlobalRiskEngine,
            RiskLevel,
            RiskEventType,
            RiskEvent,
            AccountRiskMetrics,
            PortfolioRiskMetrics,
            get_global_risk_engine,
            reset_global_risk_engine,
        )
        _ENGINE_AVAILABLE = True
        logger.debug("GlobalRiskEngine loaded via fallback direct import")
    except ImportError:
        _ENGINE_AVAILABLE = False
        GlobalRiskEngine = None  # type: ignore[assignment,misc]
        RiskLevel = None  # type: ignore[assignment,misc]
        RiskEventType = None  # type: ignore[assignment,misc]
        RiskEvent = None  # type: ignore[assignment,misc]
        AccountRiskMetrics = None  # type: ignore[assignment,misc]
        PortfolioRiskMetrics = None  # type: ignore[assignment,misc]
        get_global_risk_engine = None  # type: ignore[assignment]
        reset_global_risk_engine = None  # type: ignore[assignment]
        logger.warning(
            "GlobalRiskEngine not available — multi-account risk aggregation disabled"
        )


__all__ = [
    "GlobalRiskEngine",
    "RiskLevel",
    "RiskEventType",
    "RiskEvent",
    "AccountRiskMetrics",
    "PortfolioRiskMetrics",
    "get_global_risk_engine",
    "reset_global_risk_engine",
    "_ENGINE_AVAILABLE",
]
