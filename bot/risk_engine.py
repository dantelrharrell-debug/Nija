"""
NIJA Risk Engine — Capital Protection
======================================

Unified capital-protection layer that integrates:

1. **GlobalRiskController** — kill-switch brain with GREEN/YELLOW/ORANGE/RED/EMERGENCY
   risk-level ladder; controls whether new entries are allowed at all.

2. **PortfolioRiskEngine** — cross-symbol correlation tracking, VaR/CVaR, sector
   concentration caps, and correlation-adjusted position sizing.

3. **RiskIntelligenceGate** — pre-entry verification: volatility scaling checks and
   correlation-weighted exposure guards.

The ``RiskEngine`` class is the single entry-point for all capital-protection
decisions.  Call ``gate_trade()`` before every order; it returns a rich
``TradeGateResult`` that tells the caller whether to proceed and, if so, how
large the adjusted position should be.

Usage
-----
::

    from bot.risk_engine import get_risk_engine

    engine = get_risk_engine()

    # Before placing an order:
    result = engine.gate_trade(
        symbol="BTC-USD",
        side="long",
        raw_size_usd=500.0,
        portfolio_value=10_000.0,
        df=price_df,          # optional – enables volatility gate
    )

    if not result.approved:
        logger.warning("Trade blocked: %s", result.reason)
        return

    execute_order(size_usd=result.adjusted_size_usd)

    # After fills:
    engine.notify_position_opened(symbol="BTC-USD", size_usd=result.adjusted_size_usd)
    engine.record_trade_result(pnl=42.0, is_winner=True)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("nija.risk_engine")

# ---------------------------------------------------------------------------
# Optional subsystem imports — each degrades gracefully if unavailable.
# ---------------------------------------------------------------------------

try:
    from global_risk_controller import (
        GlobalRiskController,
        RiskLevel,
        get_global_risk_controller,
    )
    _GRC_AVAILABLE = True
except ImportError:
    try:
        from bot.global_risk_controller import (
            GlobalRiskController,
            RiskLevel,
            get_global_risk_controller,
        )
        _GRC_AVAILABLE = True
    except ImportError:
        _GRC_AVAILABLE = False
        GlobalRiskController = None  # type: ignore
        RiskLevel = None  # type: ignore
        get_global_risk_controller = None  # type: ignore
        logger.warning("GlobalRiskController not available — kill-switch checks disabled")

try:
    from portfolio_risk_engine import (
        PortfolioRiskEngine,
        get_portfolio_risk_engine,
    )
    _PRE_AVAILABLE = True
except ImportError:
    try:
        from bot.portfolio_risk_engine import (
            PortfolioRiskEngine,
            get_portfolio_risk_engine,
        )
        _PRE_AVAILABLE = True
    except ImportError:
        _PRE_AVAILABLE = False
        PortfolioRiskEngine = None  # type: ignore
        get_portfolio_risk_engine = None  # type: ignore
        logger.warning("PortfolioRiskEngine not available — correlation guards disabled")

try:
    from risk_intelligence_gate import RiskIntelligenceGate
    _RIG_AVAILABLE = True
except ImportError:
    try:
        from bot.risk_intelligence_gate import RiskIntelligenceGate
        _RIG_AVAILABLE = True
    except ImportError:
        _RIG_AVAILABLE = False
        RiskIntelligenceGate = None  # type: ignore
        logger.warning("RiskIntelligenceGate not available — pre-entry volatility gate disabled")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CapitalFloor:
    """Absolute minimum capital that must be preserved at all times."""

    floor_usd: float = 500.0          # Hard stop: halt all new entries below this
    warning_usd: float = 750.0        # Soft warning: reduce position sizes
    critical_pct_of_peak: float = 0.75  # 25 % drawdown from peak → ORANGE escalation


@dataclass
class TradeGateResult:
    """
    Decision returned by ``RiskEngine.gate_trade()``.

    Attributes
    ----------
    approved:
        ``True`` if the trade may proceed.
    adjusted_size_usd:
        Position size after all capital-protection adjustments.  Always ≤
        ``raw_size_usd``.  May be 0.0 when ``approved`` is ``False``.
    size_multiplier:
        Ratio ``adjusted_size_usd / raw_size_usd`` (0.0 – 1.0).
    reason:
        Human-readable explanation of the gate decision.
    risk_level:
        Current system risk level string (e.g. ``"GREEN"``, ``"RED"``).
    checks_passed:
        Ordered list of check names that were evaluated.
    checks_failed:
        Ordered list of check names that blocked or reduced the trade.
    timestamp:
        UTC datetime when the gate was evaluated.
    """

    approved: bool
    adjusted_size_usd: float
    size_multiplier: float
    reason: str
    risk_level: str = "UNKNOWN"
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary (JSON-safe)."""
        return {
            "approved": self.approved,
            "adjusted_size_usd": self.adjusted_size_usd,
            "size_multiplier": round(self.size_multiplier, 4),
            "reason": self.reason,
            "risk_level": self.risk_level,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Unified capital-protection engine.

    Thread-safe; intended to be used as a process-wide singleton via
    ``get_risk_engine()``.

    Parameters
    ----------
    capital_floor:
        Hard/soft balance floors.  If ``None``, defaults are used.
    max_single_position_pct:
        Maximum fraction of ``portfolio_value`` for any single trade
        (default 0.20 → 20 %).
    max_total_exposure_pct:
        Maximum total portfolio exposure across all open positions
        (default 0.80 → 80 %).
    """

    def __init__(
        self,
        capital_floor: Optional[CapitalFloor] = None,
        max_single_position_pct: float = 0.20,
        max_total_exposure_pct: float = 0.80,
    ) -> None:
        self._floor = capital_floor or CapitalFloor()
        self._max_single_pct = max_single_position_pct
        self._max_total_pct = max_total_exposure_pct
        self._lock = threading.Lock()

        # Subsystem handles
        self._grc: Optional[GlobalRiskController] = (
            get_global_risk_controller() if _GRC_AVAILABLE else None
        )
        self._pre: Optional[PortfolioRiskEngine] = (
            get_portfolio_risk_engine() if _PRE_AVAILABLE else None
        )
        self._rig: Optional[RiskIntelligenceGate] = (
            RiskIntelligenceGate(portfolio_risk_engine=self._pre)
            if _RIG_AVAILABLE
            else None
        )

        # Internal bookkeeping
        self._current_balance: float = 0.0
        self._peak_balance: float = 0.0
        self._total_exposure_usd: float = 0.0

        logger.info(
            "RiskEngine initialised | floor=$%.2f | max_pos=%.0f%% | max_exp=%.0f%%",
            self._floor.floor_usd,
            max_single_position_pct * 100,
            max_total_exposure_pct * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def gate_trade(
        self,
        symbol: str,
        side: str,
        raw_size_usd: float,
        portfolio_value: float,
        df: Optional[pd.DataFrame] = None,
        direction: str = "long",
    ) -> TradeGateResult:
        """
        Evaluate all capital-protection checks for a proposed trade.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        side:
            ``"buy"`` / ``"sell"`` (order side).
        raw_size_usd:
            Requested position size before risk adjustments.
        portfolio_value:
            Current total portfolio value in USD.
        df:
            Recent OHLCV price DataFrame (used by the volatility gate).
        direction:
            ``"long"`` or ``"short"``.

        Returns
        -------
        TradeGateResult
        """
        with self._lock:
            checks_passed: List[str] = []
            checks_failed: List[str] = []
            adjusted = raw_size_usd
            risk_level_str = "UNKNOWN"

            # ── 1. Kill-switch / global risk level ──────────────────────
            if self._grc is not None:
                risk_level_str = self._grc.current_level.value if hasattr(self._grc, "current_level") else "UNKNOWN"
                if not self._grc.is_trading_allowed():
                    return TradeGateResult(
                        approved=False,
                        adjusted_size_usd=0.0,
                        size_multiplier=0.0,
                        reason=f"Kill-switch active — risk level {risk_level_str}",
                        risk_level=risk_level_str,
                        checks_passed=checks_passed,
                        checks_failed=["kill_switch"],
                    )
                checks_passed.append("kill_switch")

                # Apply GRC position-size multiplier (e.g. YELLOW → 0.5×)
                grc_multiplier = self._grc.get_position_size_multiplier()
                if grc_multiplier < 1.0:
                    adjusted *= grc_multiplier
                    checks_failed.append(f"grc_size_reduction({grc_multiplier:.2f}x)")
                else:
                    checks_passed.append("grc_size_multiplier")

            # ── 2. Capital floor guard ───────────────────────────────────
            if self._current_balance > 0:
                if self._current_balance < self._floor.floor_usd:
                    return TradeGateResult(
                        approved=False,
                        adjusted_size_usd=0.0,
                        size_multiplier=0.0,
                        reason=(
                            f"Balance ${self._current_balance:.2f} below capital floor "
                            f"${self._floor.floor_usd:.2f}"
                        ),
                        risk_level=risk_level_str,
                        checks_passed=checks_passed,
                        checks_failed=checks_failed + ["capital_floor"],
                    )
                checks_passed.append("capital_floor")

                # Soft warning: reduce size when approaching floor
                if self._current_balance < self._floor.warning_usd:
                    warning_multiplier = 0.5
                    adjusted *= warning_multiplier
                    checks_failed.append(f"floor_warning({warning_multiplier:.2f}x)")

            # ── 3. Single-position size cap ──────────────────────────────
            max_position_usd = portfolio_value * self._max_single_pct
            if adjusted > max_position_usd:
                adjusted = max_position_usd
                checks_failed.append(
                    f"single_position_cap({self._max_single_pct:.0%} of ${portfolio_value:.0f})"
                )
            else:
                checks_passed.append("single_position_cap")

            # ── 4. Total exposure cap ────────────────────────────────────
            max_total_usd = portfolio_value * self._max_total_pct
            remaining_capacity = max(0.0, max_total_usd - self._total_exposure_usd)
            if adjusted > remaining_capacity:
                if remaining_capacity <= 0:
                    return TradeGateResult(
                        approved=False,
                        adjusted_size_usd=0.0,
                        size_multiplier=0.0,
                        reason=(
                            f"Total exposure cap reached: ${self._total_exposure_usd:.0f} "
                            f"≥ {self._max_total_pct:.0%} of ${portfolio_value:.0f}"
                        ),
                        risk_level=risk_level_str,
                        checks_passed=checks_passed,
                        checks_failed=checks_failed + ["total_exposure_cap"],
                    )
                adjusted = remaining_capacity
                checks_failed.append(
                    f"total_exposure_cap(remaining=${remaining_capacity:.0f})"
                )
            else:
                checks_passed.append("total_exposure_cap")

            # ── 5. Portfolio correlation / concentration check ───────────
            if self._pre is not None:
                try:
                    raw_pct = (adjusted / portfolio_value) if portfolio_value > 0 else 0.0
                    adj_pct = self._pre.get_position_size_adjustment(
                        symbol=symbol,
                        base_size_pct=raw_pct,
                        portfolio_value=portfolio_value,
                    )
                    if portfolio_value > 0 and raw_pct > 0 and adj_pct < raw_pct:
                        adj_factor = adj_pct / raw_pct
                        adjusted = portfolio_value * adj_pct
                        checks_failed.append(f"correlation_adjustment({adj_factor:.2f}x)")
                    else:
                        checks_passed.append("correlation_check")
                except Exception as exc:
                    logger.debug("PortfolioRiskEngine.get_position_size_adjustment error: %s", exc)

            # ── 6. Pre-entry intelligence gate (volatility scaling) ──────
            if self._rig is not None and df is not None:
                try:
                    gate_ok, gate_reason = self._rig.check_volatility_gate(
                        symbol=symbol, df=df
                    )
                    if not gate_ok:
                        return TradeGateResult(
                            approved=False,
                            adjusted_size_usd=0.0,
                            size_multiplier=0.0,
                            reason=f"Volatility gate: {gate_reason}",
                            risk_level=risk_level_str,
                            checks_passed=checks_passed,
                            checks_failed=checks_failed + ["volatility_gate"],
                        )
                    checks_passed.append("volatility_gate")
                except Exception as exc:
                    logger.debug("RiskIntelligenceGate error (non-fatal): %s", exc)

            # ── Final decision ───────────────────────────────────────────
            adjusted = max(0.0, adjusted)
            multiplier = (adjusted / raw_size_usd) if raw_size_usd > 0 else 0.0

            reason_parts = []
            if checks_failed:
                reason_parts.append("Adjustments: " + ", ".join(checks_failed))
            if not reason_parts:
                reason_parts.append("All checks passed")

            return TradeGateResult(
                approved=True,
                adjusted_size_usd=round(adjusted, 2),
                size_multiplier=round(multiplier, 4),
                reason="; ".join(reason_parts),
                risk_level=risk_level_str,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def update_balance(self, balance: float) -> None:
        """Notify the engine of the latest account balance."""
        with self._lock:
            self._current_balance = balance
            if balance > self._peak_balance:
                self._peak_balance = balance
            if self._grc is not None:
                self._grc.update_balance(balance)

    def notify_position_opened(self, symbol: str, size_usd: float) -> None:
        """Register an opened position so exposure tracking stays current."""
        with self._lock:
            self._total_exposure_usd += size_usd
            if self._pre is not None:
                try:
                    self._pre.add_position(
                        symbol=symbol,
                        size_usd=size_usd,
                        portfolio_value=max(self._current_balance, size_usd),
                        direction="long",
                        entry_time=datetime.utcnow(),
                    )
                except Exception as exc:
                    logger.debug("PortfolioRiskEngine.add_position error: %s", exc)

    def notify_position_closed(self, symbol: str, size_usd: float) -> None:
        """De-register a closed position from exposure tracking."""
        with self._lock:
            self._total_exposure_usd = max(0.0, self._total_exposure_usd - size_usd)
            if self._pre is not None:
                try:
                    self._pre.remove_position(symbol)
                except Exception as exc:
                    logger.debug("PortfolioRiskEngine.remove_position error: %s", exc)

    def record_trade_result(self, pnl: float, is_winner: bool) -> None:
        """Forward trade outcome to GlobalRiskController for auto-escalation."""
        if self._grc is not None:
            self._grc.record_trade_result(pnl=pnl, is_winner=is_winner)

    def record_api_error(self) -> None:
        """Forward API error count to GlobalRiskController."""
        if self._grc is not None:
            self._grc.record_api_error()

    def record_api_success(self) -> None:
        """Forward API success count to GlobalRiskController."""
        if self._grc is not None:
            self._grc.record_api_success()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot of the engine."""
        with self._lock:
            grc_status = self._grc.get_status() if self._grc is not None else {}
            pre_stats = self._pre.get_stats() if self._pre is not None else {}

            drawdown_pct = 0.0
            if self._peak_balance > 0 and self._current_balance < self._peak_balance:
                drawdown_pct = (
                    (self._peak_balance - self._current_balance) / self._peak_balance
                ) * 100

            return {
                "engine": "RiskEngine",
                "version": "1.0",
                "timestamp": datetime.utcnow().isoformat(),
                "capital": {
                    "current_balance_usd": self._current_balance,
                    "peak_balance_usd": self._peak_balance,
                    "drawdown_pct": round(drawdown_pct, 2),
                    "total_exposure_usd": round(self._total_exposure_usd, 2),
                    "floor_usd": self._floor.floor_usd,
                    "warning_usd": self._floor.warning_usd,
                },
                "config": {
                    "max_single_position_pct": self._max_single_pct,
                    "max_total_exposure_pct": self._max_total_pct,
                },
                "subsystems": {
                    "global_risk_controller": grc_status,
                    "portfolio_risk_engine": pre_stats,
                    "risk_intelligence_gate": _RIG_AVAILABLE,
                },
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[RiskEngine] = None
_engine_lock = threading.Lock()


def get_risk_engine(
    capital_floor: Optional[CapitalFloor] = None,
    max_single_position_pct: float = 0.20,
    max_total_exposure_pct: float = 0.80,
) -> RiskEngine:
    """
    Return the process-wide ``RiskEngine`` singleton.

    Parameters are only applied on first creation; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = RiskEngine(
                capital_floor=capital_floor,
                max_single_position_pct=max_single_position_pct,
                max_total_exposure_pct=max_total_exposure_pct,
            )
        return _engine_instance


__all__ = [
    "CapitalFloor",
    "TradeGateResult",
    "RiskEngine",
    "get_risk_engine",
]
