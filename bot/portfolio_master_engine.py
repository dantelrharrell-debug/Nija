"""
NIJA Portfolio Master Engine — Global Risk Brain
=================================================

The Portfolio Master Engine is the **central command layer** that aggregates
signals from every risk subsystem and produces a single authoritative
portfolio-level verdict for each proposed trade.

It acts as the "risk brain" that:

1. **Aggregates** verdicts from GlobalRiskGovernor, PortfolioRiskEngine,
   CorrelationRiskEngine, DynamicPositionConcentration, and VolatilityShock-
   Detector into one consolidated risk score (0–100).
2. **Enforces** hard portfolio-level limits: max gross exposure, max sector
   exposure, max drawdown, and daily-loss ceiling.
3. **Emits** structured ``PortfolioRiskReport`` objects that any downstream
   consumer (strategy, execution layer, dashboard) can inspect.
4. **Manages** the lifecycle of every open position so that real-time
   portfolio metrics remain accurate without relying on external state.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────────┐
  │                   PortfolioMasterEngine                          │
  │                                                                  │
  │  ┌─────────────────┐   ┌──────────────────┐                    │
  │  │ GlobalRiskGov.  │   │ PortfolioRiskEng. │                    │
  │  └────────┬────────┘   └────────┬─────────┘                    │
  │           │                     │                                │
  │  ┌────────▼────────┐   ┌────────▼────────┐                     │
  │  │ CorrelationRisk │   │ DynConcentration │                     │
  │  └────────┬────────┘   └────────┬─────────┘                    │
  │           │                     │                                │
  │           └──────────┬──────────┘                               │
  │                      ▼                                           │
  │          ┌───────────────────────┐                              │
  │          │  Risk Score Aggregator│ → composite 0–100            │
  │          │  Hard Limit Checker   │ → allow / block              │
  │          └───────────────────────┘                              │
  └─────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.portfolio_master_engine import get_portfolio_master_engine

    engine = get_portfolio_master_engine()

    # Before placing an order:
    report = engine.evaluate_entry(
        symbol="BTC-USD",
        side="long",
        proposed_size_usd=500.0,
        portfolio_value_usd=20_000.0,
    )

    if not report.approved:
        print(f"Blocked: {report.block_reason}")
    else:
        print(f"Approved — risk score {report.risk_score:.1f}/100")
        print(f"Max safe size: ${report.approved_size_usd:.2f}")

    # After a position opens:
    engine.register_position(symbol="BTC-USD", size_usd=500.0, side="long")

    # After a position closes:
    engine.close_position(symbol="BTC-USD", pnl_usd=42.0)

    # Dashboard snapshot:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.portfolio_master")

# ---------------------------------------------------------------------------
# Optional subsystem imports — each degrades gracefully if unavailable.
# ---------------------------------------------------------------------------

try:
    from global_risk_governor import get_global_risk_governor
    _GRG_AVAILABLE = True
except ImportError:
    try:
        from bot.global_risk_governor import get_global_risk_governor
        _GRG_AVAILABLE = True
    except ImportError:
        _GRG_AVAILABLE = False
        get_global_risk_governor = None  # type: ignore
        logger.warning("GlobalRiskGovernor not available — governor gate disabled")

try:
    from correlation_risk_engine import get_correlation_risk_engine
    _CRE_AVAILABLE = True
except ImportError:
    try:
        from bot.correlation_risk_engine import get_correlation_risk_engine
        _CRE_AVAILABLE = True
    except ImportError:
        _CRE_AVAILABLE = False
        get_correlation_risk_engine = None  # type: ignore
        logger.warning("CorrelationRiskEngine not available — correlation gate disabled")

try:
    from dynamic_position_concentration import get_dynamic_position_concentration
    _DPC_AVAILABLE = True
except ImportError:
    try:
        from bot.dynamic_position_concentration import get_dynamic_position_concentration
        _DPC_AVAILABLE = True
    except ImportError:
        _DPC_AVAILABLE = False
        get_dynamic_position_concentration = None  # type: ignore
        logger.warning("DynamicPositionConcentration not available — concentration gate disabled")

try:
    from volatility_shock_detector import get_volatility_shock_detector
    _VSD_AVAILABLE = True
except ImportError:
    try:
        from bot.volatility_shock_detector import get_volatility_shock_detector
        _VSD_AVAILABLE = True
    except ImportError:
        _VSD_AVAILABLE = False
        get_volatility_shock_detector = None  # type: ignore
        logger.warning("VolatilityShockDetector not available — volatility gate disabled")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OpenPosition:
    """Lightweight record of a tracked open position."""
    symbol: str
    side: str                    # "long" | "short"
    size_usd: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PortfolioRiskReport:
    """Consolidated verdict returned by ``evaluate_entry``."""
    symbol: str
    side: str
    proposed_size_usd: float
    approved: bool
    approved_size_usd: float     # may be reduced from proposed
    risk_score: float            # 0 (safe) – 100 (extreme risk)
    block_reason: Optional[str]  # populated when approved=False
    gate_verdicts: Dict[str, str] = field(default_factory=dict)
    portfolio_snapshot: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# PortfolioMasterEngine
# ---------------------------------------------------------------------------


class PortfolioMasterEngine:
    """
    Global risk brain — aggregates all risk subsystems into one verdict.

    Parameters
    ----------
    max_gross_exposure_pct : float
        Maximum allowed gross notional exposure as a fraction of portfolio
        value.  E.g. 0.80 = 80 %.
    max_single_position_pct : float
        Maximum allowed single-symbol notional as a fraction of portfolio
        value.
    max_daily_loss_pct : float
        Hard daily loss ceiling.  Once breached no new entries are approved.
    max_drawdown_pct : float
        Peak-to-trough drawdown limit.
    risk_score_block_threshold : float
        Composite risk score at or above which entries are blocked (0–100).
    risk_score_reduce_threshold : float
        Composite risk score at or above which position size is halved.
    """

    def __init__(
        self,
        max_gross_exposure_pct: float = 0.80,
        max_single_position_pct: float = 0.20,
        max_daily_loss_pct: float = 0.05,
        max_drawdown_pct: float = 0.20,
        risk_score_block_threshold: float = 75.0,
        risk_score_reduce_threshold: float = 50.0,
    ) -> None:
        self._lock = threading.Lock()

        # Config
        self._max_gross_pct = max_gross_exposure_pct
        self._max_single_pct = max_single_position_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._max_drawdown_pct = max_drawdown_pct
        self._block_threshold = risk_score_block_threshold
        self._reduce_threshold = risk_score_reduce_threshold

        # Portfolio state
        self._open_positions: Dict[str, OpenPosition] = {}
        self._peak_value: float = 0.0
        self._daily_pnl: float = 0.0
        self._total_pnl: float = 0.0
        self._trade_count: int = 0

        # Lazy-initialised subsystem handles
        self._grg = None   # GlobalRiskGovernor
        self._cre = None   # CorrelationRiskEngine
        self._dpc = None   # DynamicPositionConcentration
        self._vsd = None   # VolatilityShockDetector

        logger.info("=" * 60)
        logger.info("🧠 Portfolio Master Engine initialised")
        logger.info("   max_gross_exposure : %.0f%%", max_gross_exposure_pct * 100)
        logger.info("   max_single_position: %.0f%%", max_single_position_pct * 100)
        logger.info("   max_daily_loss     : %.1f%%", max_daily_loss_pct * 100)
        logger.info("   risk_block_score   : %.0f", risk_score_block_threshold)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Subsystem accessors (lazy init, thread-safe)
    # ------------------------------------------------------------------

    def _get_grg(self):
        if self._grg is None and _GRG_AVAILABLE:
            try:
                self._grg = get_global_risk_governor()
            except Exception:
                pass
        return self._grg

    def _get_cre(self):
        if self._cre is None and _CRE_AVAILABLE:
            try:
                self._cre = get_correlation_risk_engine()
            except Exception:
                pass
        return self._cre

    def _get_dpc(self):
        if self._dpc is None and _DPC_AVAILABLE:
            try:
                self._dpc = get_dynamic_position_concentration()
            except Exception:
                pass
        return self._dpc

    def _get_vsd(self):
        if self._vsd is None and _VSD_AVAILABLE:
            try:
                self._vsd = get_volatility_shock_detector()
            except Exception:
                pass
        return self._vsd

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_entry(
        self,
        symbol: str,
        side: str,
        proposed_size_usd: float,
        portfolio_value_usd: float,
    ) -> PortfolioRiskReport:
        """
        Evaluate whether a new position entry is safe.

        Returns a ``PortfolioRiskReport`` with ``approved``, ``approved_size_usd``,
        ``risk_score``, and per-gate verdicts.
        """
        with self._lock:
            verdicts: Dict[str, str] = {}
            risk_components: List[float] = []
            block_reason: Optional[str] = None

            # ── 1. Hard exposure limit ─────────────────────────────────
            gross_exposure = sum(p.size_usd for p in self._open_positions.values())
            if portfolio_value_usd > 0:
                gross_pct = (gross_exposure + proposed_size_usd) / portfolio_value_usd
            else:
                gross_pct = 1.0

            if gross_pct > self._max_gross_pct:
                verdicts["exposure"] = "BLOCKED"
                block_reason = (
                    f"Gross exposure {gross_pct * 100:.1f}% exceeds limit "
                    f"{self._max_gross_pct * 100:.0f}%"
                )
            else:
                exp_score = min(100.0, (gross_pct / self._max_gross_pct) * 100)
                risk_components.append(exp_score)
                verdicts["exposure"] = f"OK ({gross_pct * 100:.1f}%)"

            # ── 2. Single-symbol cap ────────────────────────────────────
            if portfolio_value_usd > 0:
                single_pct = proposed_size_usd / portfolio_value_usd
            else:
                single_pct = 1.0

            if single_pct > self._max_single_pct:
                verdicts["single_position"] = "BLOCKED"
                block_reason = block_reason or (
                    f"Single position {single_pct * 100:.1f}% exceeds limit "
                    f"{self._max_single_pct * 100:.0f}%"
                )
            else:
                sp_score = min(100.0, (single_pct / self._max_single_pct) * 100)
                risk_components.append(sp_score)
                verdicts["single_position"] = f"OK ({single_pct * 100:.1f}%)"

            # ── 3. Daily loss gate ──────────────────────────────────────
            if portfolio_value_usd > 0:
                daily_loss_pct = -self._daily_pnl / portfolio_value_usd
            else:
                daily_loss_pct = 0.0

            if daily_loss_pct > self._max_daily_loss_pct:
                verdicts["daily_loss"] = "BLOCKED"
                block_reason = block_reason or (
                    f"Daily loss {daily_loss_pct * 100:.2f}% exceeds limit "
                    f"{self._max_daily_loss_pct * 100:.1f}%"
                )
            else:
                dl_score = min(100.0, (daily_loss_pct / max(self._max_daily_loss_pct, 1e-9)) * 100)
                risk_components.append(dl_score)
                verdicts["daily_loss"] = f"OK ({daily_loss_pct * 100:.2f}%)"

            # ── 4. Drawdown gate ────────────────────────────────────────
            if self._peak_value > 0 and portfolio_value_usd < self._peak_value:
                dd_pct = (self._peak_value - portfolio_value_usd) / self._peak_value
            else:
                dd_pct = 0.0
                if portfolio_value_usd > self._peak_value:
                    self._peak_value = portfolio_value_usd

            if dd_pct > self._max_drawdown_pct:
                verdicts["drawdown"] = "BLOCKED"
                block_reason = block_reason or (
                    f"Drawdown {dd_pct * 100:.2f}% exceeds limit "
                    f"{self._max_drawdown_pct * 100:.0f}%"
                )
            else:
                dd_score = min(100.0, (dd_pct / max(self._max_drawdown_pct, 1e-9)) * 100)
                risk_components.append(dd_score)
                verdicts["drawdown"] = f"OK ({dd_pct * 100:.2f}%)"

            # ── 5. GlobalRiskGovernor gate ──────────────────────────────
            grg = self._get_grg()
            if grg is not None:
                try:
                    decision = grg.approve_entry(
                        symbol=symbol,
                        proposed_risk_usd=proposed_size_usd * 0.01,
                        current_portfolio_value=portfolio_value_usd,
                    )
                    if not decision.allowed:
                        verdicts["governor"] = f"BLOCKED ({decision.reason})"
                        block_reason = block_reason or f"Governor: {decision.reason}"
                    else:
                        verdicts["governor"] = "OK"
                        risk_components.append(decision.risk_score)
                except Exception as exc:
                    verdicts["governor"] = f"ERROR ({exc})"
            else:
                verdicts["governor"] = "UNAVAILABLE"

            # ── 6. CorrelationRiskEngine gate ───────────────────────────
            cre = self._get_cre()
            if cre is not None:
                try:
                    ok = cre.approve_entry(symbol=symbol)
                    verdicts["correlation"] = "OK" if ok else "BLOCKED"
                    if not ok:
                        block_reason = block_reason or "Correlation cluster limit reached"
                    else:
                        risk_components.append(30.0)
                except Exception as exc:
                    verdicts["correlation"] = f"ERROR ({exc})"
            else:
                verdicts["correlation"] = "UNAVAILABLE"

            # ── 7. DynamicPositionConcentration gate ────────────────────
            dpc = self._get_dpc()
            if dpc is not None:
                try:
                    result = dpc.approve_entry(symbol=symbol, size_usd=proposed_size_usd)
                    if not result.approved:
                        verdicts["concentration"] = f"BLOCKED ({result.reason})"
                        block_reason = block_reason or f"Concentration: {result.reason}"
                    else:
                        verdicts["concentration"] = "OK"
                        risk_components.append(25.0)
                except Exception as exc:
                    verdicts["concentration"] = f"ERROR ({exc})"
            else:
                verdicts["concentration"] = "UNAVAILABLE"

            # ── 8. VolatilityShockDetector gate ─────────────────────────
            vsd = self._get_vsd()
            if vsd is not None:
                try:
                    shock = vsd.get_portfolio_shock()
                    severity = getattr(shock, "severity", "NONE")
                    size_scale = getattr(shock, "size_scale", 1.0)
                    verdicts["volatility"] = f"OK ({severity})"
                    if severity in ("SEVERE", "EXTREME"):
                        if size_scale == 0.0:
                            verdicts["volatility"] = f"BLOCKED ({severity})"
                            block_reason = block_reason or f"Volatility shock: {severity}"
                        else:
                            proposed_size_usd = proposed_size_usd * size_scale
                    risk_components.append(min(100.0, (1.0 - size_scale) * 100))
                except Exception as exc:
                    verdicts["volatility"] = f"ERROR ({exc})"
            else:
                verdicts["volatility"] = "UNAVAILABLE"

            # ── Composite risk score ────────────────────────────────────
            risk_score = (
                sum(risk_components) / len(risk_components)
                if risk_components
                else 0.0
            )

            # ── Final verdict ───────────────────────────────────────────
            if block_reason:
                approved = False
                approved_size = 0.0
            elif risk_score >= self._block_threshold:
                approved = False
                approved_size = 0.0
                block_reason = f"Composite risk score {risk_score:.1f} ≥ block threshold {self._block_threshold:.0f}"
            elif risk_score >= self._reduce_threshold:
                approved = True
                approved_size = proposed_size_usd * 0.5
            else:
                approved = True
                approved_size = proposed_size_usd

            portfolio_snapshot = {
                "open_positions": len(self._open_positions),
                "gross_exposure_usd": round(gross_exposure, 2),
                "gross_exposure_pct": round(gross_pct * 100, 2),
                "daily_pnl_usd": round(self._daily_pnl, 2),
                "drawdown_pct": round(dd_pct * 100, 2),
            }

            return PortfolioRiskReport(
                symbol=symbol,
                side=side,
                proposed_size_usd=proposed_size_usd,
                approved=approved,
                approved_size_usd=round(approved_size, 2),
                risk_score=round(risk_score, 2),
                block_reason=block_reason,
                gate_verdicts=verdicts,
                portfolio_snapshot=portfolio_snapshot,
            )

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def register_position(
        self,
        symbol: str,
        size_usd: float,
        side: str = "long",
    ) -> None:
        """Record an opened position in portfolio state."""
        with self._lock:
            self._open_positions[symbol] = OpenPosition(
                symbol=symbol, side=side, size_usd=size_usd
            )
            logger.debug("Position registered: %s %s $%.2f", side, symbol, size_usd)

    def close_position(self, symbol: str, pnl_usd: float = 0.0) -> None:
        """Remove a closed position and update P&L accounting."""
        with self._lock:
            self._open_positions.pop(symbol, None)
            self._daily_pnl += pnl_usd
            self._total_pnl += pnl_usd
            self._trade_count += 1
            logger.debug(
                "Position closed: %s | P&L $%.2f | total P&L $%.2f",
                symbol, pnl_usd, self._total_pnl,
            )

    def reset_daily_pnl(self) -> None:
        """Reset daily P&L counter — should be called at the start of each session."""
        with self._lock:
            self._daily_pnl = 0.0

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of portfolio master state."""
        with self._lock:
            gross_exposure = sum(p.size_usd for p in self._open_positions.values())
            return {
                "engine": "PortfolioMasterEngine",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "open_positions": len(self._open_positions),
                "gross_exposure_usd": round(gross_exposure, 2),
                "daily_pnl_usd": round(self._daily_pnl, 2),
                "total_pnl_usd": round(self._total_pnl, 2),
                "trade_count": self._trade_count,
                "peak_portfolio_value": round(self._peak_value, 2),
                "config": {
                    "max_gross_exposure_pct": self._max_gross_pct,
                    "max_single_position_pct": self._max_single_pct,
                    "max_daily_loss_pct": self._max_daily_loss_pct,
                    "max_drawdown_pct": self._max_drawdown_pct,
                    "risk_score_block_threshold": self._block_threshold,
                    "risk_score_reduce_threshold": self._reduce_threshold,
                },
                "subsystems": {
                    "global_risk_governor": _GRG_AVAILABLE,
                    "correlation_risk_engine": _CRE_AVAILABLE,
                    "dynamic_position_concentration": _DPC_AVAILABLE,
                    "volatility_shock_detector": _VSD_AVAILABLE,
                },
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[PortfolioMasterEngine] = None
_instance_lock = threading.Lock()


def get_portfolio_master_engine(**kwargs) -> PortfolioMasterEngine:
    """
    Return the process-wide ``PortfolioMasterEngine`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = PortfolioMasterEngine(**kwargs)
        return _instance


__all__ = [
    "OpenPosition",
    "PortfolioRiskReport",
    "PortfolioMasterEngine",
    "get_portfolio_master_engine",
]
