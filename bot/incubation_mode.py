"""
NIJA Disciplined Incubation Mode
==================================
Bundles and enforces the "incubation mode" risk profile:

  • Spot trading only (no shorts / futures)
  • 0.5 %–1 % risk per trade
  • Max 5–8 concurrent positions
  • 40 % max correlation-group cap
  • ATR-adjusted sizing active (via VolatilityAdaptiveSizer)
  • VaR breach auto-size reduction (via VaRAutoSizeReducer)
  • Drawdown circuit breaker enforced (via DrawdownCircuitBreaker)

Usage
-----
Activate incubation mode by setting the environment variable::

    INCUBATION_MODE=true

Then obtain the pre-configured components::

    from bot.incubation_mode import get_incubation_config

    cfg = get_incubation_config(account_balance=10_000.0)
    # cfg.risk_intelligence_system  → RiskIntelligenceSystem
    # cfg.max_positions             → 8
    # cfg.min_risk_pct              → 0.5
    # cfg.max_risk_pct              → 1.0
    # cfg.spot_only                 → True
    # cfg.is_active                 → True

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("nija.incubation_mode")

# ---------------------------------------------------------------------------
# Optional dependency imports (graceful degradation)
# ---------------------------------------------------------------------------
try:
    from bot.risk_intelligence import RiskIntelligenceSystem, create_risk_intelligence_system
    _HAS_RISK_INTELLIGENCE = True
except ImportError:
    try:
        from risk_intelligence import RiskIntelligenceSystem, create_risk_intelligence_system  # type: ignore
        _HAS_RISK_INTELLIGENCE = True
    except ImportError:
        RiskIntelligenceSystem = None  # type: ignore
        create_risk_intelligence_system = None  # type: ignore
        _HAS_RISK_INTELLIGENCE = False
        logger.warning("⚠️ RiskIntelligenceSystem not available — incubation mode controls degraded")

try:
    from bot.portfolio_var_monitor import PortfolioVaRMonitor, VaRAutoSizeReducer, get_portfolio_var_monitor
    _HAS_VAR_MONITOR = True
except ImportError:
    try:
        from portfolio_var_monitor import PortfolioVaRMonitor, VaRAutoSizeReducer, get_portfolio_var_monitor  # type: ignore
        _HAS_VAR_MONITOR = True
    except ImportError:
        PortfolioVaRMonitor = None  # type: ignore
        VaRAutoSizeReducer = None  # type: ignore
        get_portfolio_var_monitor = None  # type: ignore
        _HAS_VAR_MONITOR = False
        logger.warning("⚠️ PortfolioVaRMonitor not available — VaR auto-size reduction disabled")

try:
    from bot.volatility_adaptive_sizer import VolatilityAdaptiveSizer
    _HAS_VOL_SIZER = True
except ImportError:
    try:
        from volatility_adaptive_sizer import VolatilityAdaptiveSizer  # type: ignore
        _HAS_VOL_SIZER = True
    except ImportError:
        VolatilityAdaptiveSizer = None  # type: ignore
        _HAS_VOL_SIZER = False
        logger.warning("⚠️ VolatilityAdaptiveSizer not available — ATR-adjusted sizing disabled")

# ---------------------------------------------------------------------------
# Incubation mode constants
# ---------------------------------------------------------------------------

#: Minimum risk per trade as a percentage of account balance.
INCUBATION_MIN_RISK_PCT: float = 0.5

#: Maximum risk per trade as a percentage of account balance.
INCUBATION_MAX_RISK_PCT: float = 1.0

#: Minimum number of concurrent positions allowed.
INCUBATION_MIN_POSITIONS: int = 5

#: Maximum number of concurrent positions allowed.
INCUBATION_MAX_POSITIONS: int = 8

#: Maximum exposure per correlation group (40 % cap).
INCUBATION_MAX_GROUP_EXPOSURE_PCT: float = 0.40

#: Drawdown percentage at which trading halts entirely.
INCUBATION_DRAWDOWN_HALT_PCT: float = 15.0

#: Drawdown percentage at which position sizes are strongly reduced.
INCUBATION_DRAWDOWN_DANGER_PCT: float = 10.0

#: Drawdown percentage that triggers a size-reduction warning.
INCUBATION_DRAWDOWN_WARNING_PCT: float = 7.0

#: Drawdown percentage that triggers a caution-level log.
INCUBATION_DRAWDOWN_CAUTION_PCT: float = 3.0

#: Position-size multiplier applied when the 95 % VaR limit is breached.
INCUBATION_VAR_MULT_95: float = 0.75

#: Position-size multiplier applied when the 99 % VaR limit is breached.
INCUBATION_VAR_MULT_99: float = 0.50

#: Monitoring cycles (without breach) needed before VaR multiplier resets.
INCUBATION_VAR_RECOVERY_CYCLES: int = 5

# Base position sizing for ATR-adjusted (volatility-adaptive) sizer.
_VOL_SIZER_CONFIG = {
    "base_position_pct": 0.01,   # 1 % of account – top of incubation range
    "min_position_pct":  0.005,  # 0.5 % of account – bottom of incubation range
    "max_position_pct":  0.01,   # hard cap at 1 %
}


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class IncubationModeConfig:
    """
    Fully initialised incubation-mode configuration.

    All sub-system objects are constructed and wired together so callers
    can use them directly.
    """

    is_active: bool = False

    # Risk per trade bounds (percentage of account balance)
    min_risk_pct: float = INCUBATION_MIN_RISK_PCT
    max_risk_pct: float = INCUBATION_MAX_RISK_PCT

    # Position limits
    min_positions: int = INCUBATION_MIN_POSITIONS
    max_positions: int = INCUBATION_MAX_POSITIONS

    # Spot-only enforcement
    spot_only: bool = True

    # Correlation cap
    max_group_exposure_pct: float = INCUBATION_MAX_GROUP_EXPOSURE_PCT

    # Sub-system objects (None when the underlying library is unavailable)
    risk_intelligence_system: Optional[object] = field(default=None, repr=False)
    var_monitor: Optional[object] = field(default=None, repr=False)
    var_size_reducer: Optional[object] = field(default=None, repr=False)
    volatility_sizer: Optional[object] = field(default=None, repr=False)

    def is_spot_trade_allowed(self, action: str) -> bool:
        """
        Return ``True`` when *action* is permitted under spot-only trading.

        ``'enter_long'`` and any BUY-side action are always allowed.
        ``'enter_short'`` and any SELL-side *opening* action are blocked.
        Exit actions (closing existing positions) are always allowed.

        Args:
            action: Trade action string (e.g. ``'enter_long'``, ``'enter_short'``).
        """
        if not self.spot_only:
            return True
        blocked = {"enter_short", "short", "sell_short", "open_short"}
        allowed = action.lower() not in blocked
        if not allowed:
            logger.warning(
                "🚫 INCUBATION MODE (spot-only): action '%s' blocked. "
                "Only long/buy positions are permitted.",
                action,
            )
        return allowed

    def check_position_count(self, current_count: int) -> bool:
        """
        Return ``True`` when a new position may be opened given *current_count*.

        Args:
            current_count: Number of currently open positions.
        """
        allowed = current_count < self.max_positions
        if not allowed:
            logger.warning(
                "🚫 INCUBATION MODE: position cap reached (%d/%d).",
                current_count,
                self.max_positions,
            )
        return allowed

    def get_summary(self) -> dict:
        """Return a human-readable summary dict for logging / API responses."""
        return {
            "mode": "INCUBATION",
            "is_active": self.is_active,
            "spot_only": self.spot_only,
            "risk_per_trade_pct": f"{self.min_risk_pct}%–{self.max_risk_pct}%",
            "max_positions": self.max_positions,
            "max_group_exposure_pct": f"{self.max_group_exposure_pct * 100:.0f}%",
            "atr_sizing": self.volatility_sizer is not None,
            "var_auto_reduce": self.var_size_reducer is not None,
            "drawdown_circuit_breaker": self.risk_intelligence_system is not None,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_incubation_config(
    account_balance: float = 10_000.0,
    var_monitor: Optional[object] = None,
) -> IncubationModeConfig:
    """
    Build and return an :class:`IncubationModeConfig`.

    If ``INCUBATION_MODE`` environment variable is not ``'true'`` (case-insensitive)
    a config with ``is_active=False`` and no sub-systems is returned, so callers
    can always call this function safely.

    Args:
        account_balance: Current portfolio value in USD (used to size the
            drawdown circuit breaker).
        var_monitor: Optional existing :class:`PortfolioVaRMonitor` instance.
            When ``None`` the module-level singleton is used (if available).

    Returns:
        :class:`IncubationModeConfig` (active or inactive).
    """
    active = os.getenv("INCUBATION_MODE", "false").strip().lower() == "true"

    if not active:
        return IncubationModeConfig(is_active=False)

    logger.info("🐣 INCUBATION MODE activating …")

    # ------------------------------------------------------------------
    # 1. ATR-adjusted position sizer
    # ------------------------------------------------------------------
    vol_sizer = None
    if _HAS_VOL_SIZER and VolatilityAdaptiveSizer is not None:
        try:
            vol_sizer = VolatilityAdaptiveSizer(config=_VOL_SIZER_CONFIG)
            logger.info("  ✅ ATR-adjusted sizing: active")
        except Exception as exc:
            logger.warning("  ⚠️ VolatilityAdaptiveSizer init failed: %s", exc)

    # ------------------------------------------------------------------
    # 2. VaR breach auto-size reducer
    # ------------------------------------------------------------------
    _var_mon = var_monitor
    var_reducer = None
    if _HAS_VAR_MONITOR and PortfolioVaRMonitor is not None and VaRAutoSizeReducer is not None:
        try:
            if _var_mon is None:
                _var_mon = get_portfolio_var_monitor()
            var_reducer = VaRAutoSizeReducer(
                var_monitor=_var_mon,
                multiplier_on_95_breach=INCUBATION_VAR_MULT_95,
                multiplier_on_99_breach=INCUBATION_VAR_MULT_99,
                recovery_cycles=INCUBATION_VAR_RECOVERY_CYCLES,
            )
            logger.info("  ✅ VaR breach auto-size reduction: active (95%%→%.0f%%, 99%%→%.0f%%)",
                        INCUBATION_VAR_MULT_95 * 100, INCUBATION_VAR_MULT_99 * 100)
        except Exception as exc:
            logger.warning("  ⚠️ VaRAutoSizeReducer init failed: %s", exc)

    # ------------------------------------------------------------------
    # 3. Risk Intelligence System (correlation cap + drawdown circuit breaker)
    # ------------------------------------------------------------------
    ris = None
    if _HAS_RISK_INTELLIGENCE and create_risk_intelligence_system is not None:
        try:
            ris = create_risk_intelligence_system(
                base_capital=account_balance,
                config={
                    "max_group_exposure_pct": INCUBATION_MAX_GROUP_EXPOSURE_PCT,
                    "drawdown_halt_pct":    INCUBATION_DRAWDOWN_HALT_PCT,
                    "drawdown_danger_pct":  INCUBATION_DRAWDOWN_DANGER_PCT,
                    "drawdown_warning_pct": INCUBATION_DRAWDOWN_WARNING_PCT,
                    "drawdown_caution_pct": INCUBATION_DRAWDOWN_CAUTION_PCT,
                },
                volatility_sizer=vol_sizer,
                var_size_reducer=var_reducer,
            )
            logger.info(
                "  ✅ Risk Intelligence System: active "
                "(correlation cap=40%%, drawdown circuit breaker=active)"
            )
        except Exception as exc:
            logger.warning("  ⚠️ RiskIntelligenceSystem init failed: %s", exc)

    cfg = IncubationModeConfig(
        is_active=True,
        min_risk_pct=INCUBATION_MIN_RISK_PCT,
        max_risk_pct=INCUBATION_MAX_RISK_PCT,
        min_positions=INCUBATION_MIN_POSITIONS,
        max_positions=INCUBATION_MAX_POSITIONS,
        spot_only=True,
        max_group_exposure_pct=INCUBATION_MAX_GROUP_EXPOSURE_PCT,
        risk_intelligence_system=ris,
        var_monitor=_var_mon,
        var_size_reducer=var_reducer,
        volatility_sizer=vol_sizer,
    )

    logger.info("🐣 INCUBATION MODE active: %s", cfg.get_summary())
    return cfg
