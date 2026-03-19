"""
NIJA Smart Reinvest Cycles
===========================

Re-deploys locked/harvested profit capital from the CapitalRecyclingEngine
pool ONLY when a set of market and system conditions are simultaneously
"perfect" — maximising the expected value of every reinvested dollar.

Conditions evaluated (all must pass)
--------------------------------------
1. Regime Gate       – Current market regime must not be in the block-list.
2. Volatility Gate   – Portfolio volatility shock must be < SEVERE.
3. Risk Governor     – GlobalRiskGovernor must not be halted.
4. Strategy Health   – Target strategy health must be ≥ WATCHING (tradeable).
5. Win Rate Gate     – Rolling win rate must be ≥ the configured floor.
6. Pool Gate         – Recycling pool must hold enough capital to deploy.
7. Cooldown Gate     – Minimum cooldown period since the last deployment.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │                  SmartReinvestCycleEngine                    │
  │                                                              │
  │  request_reinvestment(strategy, regime, base_position_usd)   │
  │                                                              │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 1 – Regime Gate                           │     │
  │  │   regime not in BLOCKED_REGIMES                     │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 2 – Volatility Gate                       │     │
  │  │   VolatilityShockDetector.get_portfolio_shock()     │     │
  │  │   severity < SEVERE  → PASS                         │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 3 – Risk Governor Gate                    │     │
  │  │   GlobalRiskGovernor.approve_entry() → allowed      │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 4 – Strategy Health Gate                  │     │
  │  │   StrategyHealthMonitor.get_health(strategy)        │     │
  │  │   is_tradeable → PASS                               │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 5 – Win Rate Gate                         │     │
  │  │   rolling win rate ≥ WIN_RATE_FLOOR                 │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 6 – Pool Gate                             │     │
  │  │   pool_usd ≥ MIN_POOL_TO_DEPLOY                     │     │
  │  └────────────────────────────────────────────────────┘     │
  │  ┌────────────────────────────────────────────────────┐     │
  │  │ Condition 7 – Cooldown Gate                         │     │
  │  │   seconds_since_last_deploy ≥ MIN_COOLDOWN_SECONDS  │     │
  │  └────────────────────────────────────────────────────┘     │
  │                                                              │
  │  All PASS → claim_allocation() → augment position size       │
  │  Any FAIL → return 0.0 (no extra capital deployed)           │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.smart_reinvest_cycles import get_smart_reinvest_engine

    engine = get_smart_reinvest_engine()

    # During trade entry, after position size is determined and validated:
    extra_usd = engine.request_reinvestment(
        strategy="ApexTrend",
        regime="BULL_TRENDING",
        base_position_usd=500.0,
        portfolio_value=10_000.0,
    )
    position_size += extra_usd   # augment with recycled capital only when perfect

    # Status / diagnostics:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.smart_reinvest_cycles")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Regimes where reinvestment is blocked regardless of other conditions.
BLOCKED_REGIMES: frozenset = frozenset(
    {
        "BREAKDOWN",
        "EXTREME_BEAR",
        "CRASH",
        "HIGHLY_VOLATILE",
        "UNKNOWN",
    }
)

#: Minimum recycling pool balance (USD) before any reinvestment is attempted.
MIN_POOL_TO_DEPLOY: float = 5.0

#: Minimum rolling win rate required for reinvestment approval.
WIN_RATE_FLOOR: float = 0.50  # 50 %

#: Minimum seconds between reinvestment deployments per strategy.
MIN_COOLDOWN_SECONDS: float = 300.0  # 5 minutes

#: Maximum extra capital as a fraction of the base position size.
MAX_REINVEST_FRACTION: float = 0.50  # 50 % of base

#: Hard cap on extra capital injected per reinvest event (USD).
MAX_REINVEST_USD: float = 500.0

#: Path to the JSON persistence file.
DEFAULT_STATE_PATH: str = "data/smart_reinvest_cycles_state.json"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ConditionStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # module unavailable — treated as passed (graceful)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConditionResult:
    """Outcome of a single reinvest condition check."""

    condition: str
    status: ConditionStatus
    score: float = 0.0  # 0–100 contribution to composite readiness score
    reason: str = ""


@dataclass
class ReinvestDecision:
    """Full decision record for one reinvest evaluation."""

    approved: bool
    strategy: str
    regime: str
    base_position_usd: float
    reinvest_usd: float          # amount actually added (0 if denied)
    readiness_score: float       # 0–100 composite
    conditions: List[ConditionResult] = field(default_factory=list)
    denied_reasons: List[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class DeployEvent:
    """A single reinvestment deployment record."""

    timestamp: str
    strategy: str
    regime: str
    amount_usd: float
    base_position_usd: float
    readiness_score: float


@dataclass
class ReinvestCycleState:
    """Persistent state for the SmartReinvestCycleEngine."""

    # Per-strategy ISO timestamp of the last successful deployment
    last_deploy_ts: Dict[str, str] = field(default_factory=dict)
    # Per-strategy cumulative USD deployed
    total_deployed: Dict[str, float] = field(default_factory=dict)
    # Aggregate counters
    total_reinvest_events: int = 0
    total_denied_events: int = 0
    total_usd_deployed: float = 0.0
    # Audit trail — capped at 200 most-recent events
    deploy_events: List[Dict] = field(default_factory=list)
    created_at: str = ""
    last_updated: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seconds_since(iso_ts: str) -> float:
    """Return elapsed seconds since *iso_ts* (UTC ISO-8601 string)."""
    try:
        then = datetime.fromisoformat(iso_ts)
        return (datetime.now(timezone.utc) - then).total_seconds()
    except Exception:
        return float("inf")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SmartReinvestCycleEngine:
    """
    Re-deploys capital from the recycling pool ONLY when all conditions
    are simultaneously "perfect".

    Parameters
    ----------
    state_path : str
        Path to the JSON persistence file.
    blocked_regimes : frozenset, optional
        Regime strings that block reinvestment.
    min_pool_to_deploy : float
        Minimum recycling pool balance required before deployment.
    win_rate_floor : float
        Minimum rolling win rate (0–1) required.
    min_cooldown_seconds : float
        Seconds to wait between deployments per strategy.
    max_reinvest_fraction : float
        Maximum extra capital as a fraction of base position size.
    max_reinvest_usd : float
        Hard cap on extra capital per reinvest event (USD).
    """

    def __init__(
        self,
        state_path: str = DEFAULT_STATE_PATH,
        blocked_regimes: frozenset = BLOCKED_REGIMES,
        min_pool_to_deploy: float = MIN_POOL_TO_DEPLOY,
        win_rate_floor: float = WIN_RATE_FLOOR,
        min_cooldown_seconds: float = MIN_COOLDOWN_SECONDS,
        max_reinvest_fraction: float = MAX_REINVEST_FRACTION,
        max_reinvest_usd: float = MAX_REINVEST_USD,
    ) -> None:
        self.state_path = state_path
        self.blocked_regimes = frozenset(str(r).upper() for r in blocked_regimes)
        self.min_pool_to_deploy = min_pool_to_deploy
        self.win_rate_floor = win_rate_floor
        self.min_cooldown_seconds = min_cooldown_seconds
        self.max_reinvest_fraction = max_reinvest_fraction
        self.max_reinvest_usd = max_reinvest_usd
        self._lock = threading.RLock()
        self._state = ReinvestCycleState(created_at=_now(), last_updated=_now())
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def request_reinvestment(
        self,
        strategy: str,
        regime: str,
        base_position_usd: float,
        portfolio_value: float = 0.0,
    ) -> float:
        """
        Evaluate all conditions and, if perfect, claim recycled capital to
        augment a position.

        Parameters
        ----------
        strategy : str
            Name of the strategy opening the position (e.g. ``"ApexTrend"``).
        regime : str
            Current market regime string.
        base_position_usd : float
            Position size already computed by the strategy's risk model.
        portfolio_value : float, optional
            Current portfolio value in USD (used for risk-governor check).

        Returns
        -------
        float
            Additional USD to add to the position.  Returns ``0.0`` if any
            condition fails or if the recycling pool is empty.
        """
        decision = self._evaluate(strategy, regime, base_position_usd, portfolio_value)

        with self._lock:
            if decision.approved and decision.reinvest_usd > 0:
                self._record_deploy(decision)
                logger.info(
                    "🔄 [SmartReinvest] APPROVED — strategy=%s regime=%s "
                    "base=$%.2f extra=$%.2f score=%.0f",
                    strategy,
                    regime,
                    base_position_usd,
                    decision.reinvest_usd,
                    decision.readiness_score,
                )
            else:
                self._state.total_denied_events += 1
                self._state.last_updated = _now()
                self._save_state()
                if decision.denied_reasons:
                    logger.debug(
                        "🔄 [SmartReinvest] DENIED — strategy=%s regime=%s reasons=%s",
                        strategy,
                        regime,
                        decision.denied_reasons,
                    )

        return decision.reinvest_usd

    def get_status(self) -> Dict:
        """Return a structured status dictionary for dashboards and APIs."""
        with self._lock:
            s = self._state
            return {
                "total_reinvest_events": s.total_reinvest_events,
                "total_denied_events": s.total_denied_events,
                "total_usd_deployed": round(s.total_usd_deployed, 4),
                "per_strategy_deployed": {
                    k: round(v, 4) for k, v in s.total_deployed.items()
                },
                "last_deploy_ts": dict(s.last_deploy_ts),
                "config": {
                    "blocked_regimes": sorted(self.blocked_regimes),
                    "min_pool_to_deploy": self.min_pool_to_deploy,
                    "win_rate_floor": self.win_rate_floor,
                    "min_cooldown_seconds": self.min_cooldown_seconds,
                    "max_reinvest_fraction": self.max_reinvest_fraction,
                    "max_reinvest_usd": self.max_reinvest_usd,
                },
                "recent_deploys": s.deploy_events[-10:],
                "created_at": s.created_at,
                "last_updated": s.last_updated,
            }

    def get_report(self) -> str:
        """Return a human-readable text report."""
        with self._lock:
            s = self._state
            lines = [
                "=" * 70,
                "  🔄  SMART REINVEST CYCLES — STATUS REPORT",
                "=" * 70,
                f"  Total Reinvest Events : {s.total_reinvest_events}",
                f"  Total Denied Events   : {s.total_denied_events}",
                f"  Total USD Deployed    : ${s.total_usd_deployed:>12,.2f}",
                "",
                "  Configuration:",
                f"    Min Pool to Deploy  : ${self.min_pool_to_deploy:.2f}",
                f"    Win Rate Floor      : {self.win_rate_floor * 100:.0f} %",
                f"    Cooldown            : {self.min_cooldown_seconds:.0f} s",
                f"    Max Extra Fraction  : {self.max_reinvest_fraction * 100:.0f} % of base",
                f"    Max Extra USD       : ${self.max_reinvest_usd:.2f}",
                f"    Blocked Regimes     : "
                f"{', '.join(sorted(self.blocked_regimes)) or 'none'}",
                "",
                "  Per-Strategy Deployed:",
            ]
            for strat, usd in sorted(
                s.total_deployed.items(), key=lambda x: x[1], reverse=True
            ):
                last_ts = s.last_deploy_ts.get(strat, "N/A")[:19]
                lines.append(
                    f"    {strat:<22s}  ${usd:>10,.2f}  last: {last_ts}"
                )
            if not s.total_deployed:
                lines.append("    (none yet)")
            lines += [
                "",
                f"  Recent Deployments ({min(5, len(s.deploy_events))} "
                f"of {len(s.deploy_events)}):",
            ]
            for ev in s.deploy_events[-5:]:
                lines.append(
                    f"    {ev.get('timestamp', '')[:19]}  "
                    f"{ev.get('strategy', ''):>22}  "
                    f"+${ev.get('amount_usd', 0):>8,.2f}  "
                    f"[{ev.get('regime', '')}]  "
                    f"score={ev.get('readiness_score', 0):.0f}"
                )
            lines.append("=" * 70)
            return "\n".join(lines)

    # ── Condition Evaluation ──────────────────────────────────────────────────

    def _evaluate(
        self,
        strategy: str,
        regime: str,
        base_position_usd: float,
        portfolio_value: float,
    ) -> ReinvestDecision:
        """Run all condition checks and build a ``ReinvestDecision``."""
        conditions: List[ConditionResult] = []
        denied_reasons: List[str] = []

        for check_fn, args in [
            (self._check_regime, (regime,)),
            (self._check_volatility, ()),
            (self._check_risk_governor, (strategy, portfolio_value)),
            (self._check_strategy_health, (strategy,)),
            (self._check_win_rate, (strategy,)),
            (self._check_pool, ()),
            (self._check_cooldown, (strategy,)),
        ]:
            result: ConditionResult = check_fn(*args)
            conditions.append(result)
            if result.status == ConditionStatus.FAILED:
                denied_reasons.append(result.reason)

        approved = len(denied_reasons) == 0

        # Composite readiness score: average of all condition scores
        readiness_score = (
            sum(c.score for c in conditions) / len(conditions)
            if conditions
            else 0.0
        )

        reinvest_usd = 0.0
        if approved:
            reinvest_usd = self._compute_reinvest_amount(
                strategy, regime, base_position_usd
            )

        return ReinvestDecision(
            approved=approved,
            strategy=strategy,
            regime=regime,
            base_position_usd=base_position_usd,
            reinvest_usd=reinvest_usd,
            readiness_score=readiness_score,
            conditions=conditions,
            denied_reasons=denied_reasons,
            timestamp=_now(),
        )

    # ── Individual Condition Checks ───────────────────────────────────────────

    def _check_regime(self, regime: str) -> ConditionResult:
        regime_upper = str(regime).upper()
        if regime_upper in self.blocked_regimes:
            return ConditionResult(
                condition="regime_gate",
                status=ConditionStatus.FAILED,
                score=0.0,
                reason=f"Regime '{regime}' is blocked for reinvestment",
            )
        return ConditionResult(
            condition="regime_gate",
            status=ConditionStatus.PASSED,
            score=100.0,
            reason=f"Regime '{regime}' is acceptable for reinvestment",
        )

    def _check_volatility(self) -> ConditionResult:
        try:
            try:
                from bot.volatility_shock_detector import (
                    get_volatility_shock_detector,
                )
            except ImportError:
                from volatility_shock_detector import get_volatility_shock_detector

            vsd = get_volatility_shock_detector()
            shock = vsd.get_portfolio_shock()
            severity = (
                shock.get("severity", "NONE")
                if isinstance(shock, dict)
                else str(shock)
            )
            if severity.upper() in {"SEVERE", "EXTREME"}:
                return ConditionResult(
                    condition="volatility_gate",
                    status=ConditionStatus.FAILED,
                    score=0.0,
                    reason=f"Portfolio volatility shock level: {severity}",
                )
            score_map = {"NONE": 100.0, "MINOR": 80.0, "MODERATE": 50.0}
            score = score_map.get(severity.upper(), 100.0)
            return ConditionResult(
                condition="volatility_gate",
                status=ConditionStatus.PASSED,
                score=score,
                reason=f"Volatility shock: {severity}",
            )
        except Exception as exc:
            logger.debug("SmartReinvest: volatility check skipped (%s)", exc)
            return ConditionResult(
                condition="volatility_gate",
                status=ConditionStatus.SKIPPED,
                score=100.0,
                reason="VolatilityShockDetector unavailable — skipped",
            )

    def _check_risk_governor(
        self, strategy: str, portfolio_value: float
    ) -> ConditionResult:
        try:
            try:
                from bot.global_risk_governor import get_global_risk_governor
            except ImportError:
                from global_risk_governor import get_global_risk_governor

            gov = get_global_risk_governor()
            decision = gov.approve_entry(
                symbol=f"REINVEST/{strategy}",
                proposed_risk_usd=0.0,
                current_portfolio_value=portfolio_value,
            )
            if not decision.allowed:
                return ConditionResult(
                    condition="risk_governor_gate",
                    status=ConditionStatus.FAILED,
                    score=0.0,
                    reason=f"Risk governor blocked: {decision.reason}",
                )
            risk_score_val = max(
                0.0, 100.0 - getattr(decision, "risk_score", 0.0)
            )
            return ConditionResult(
                condition="risk_governor_gate",
                status=ConditionStatus.PASSED,
                score=risk_score_val,
                reason="Risk governor approved",
            )
        except Exception as exc:
            logger.debug("SmartReinvest: risk governor check skipped (%s)", exc)
            return ConditionResult(
                condition="risk_governor_gate",
                status=ConditionStatus.SKIPPED,
                score=100.0,
                reason="GlobalRiskGovernor unavailable — skipped",
            )

    def _check_strategy_health(self, strategy: str) -> ConditionResult:
        try:
            try:
                from bot.strategy_health_monitor import get_strategy_health_monitor
            except ImportError:
                from strategy_health_monitor import get_strategy_health_monitor

            monitor = get_strategy_health_monitor()
            health = monitor.get_health(strategy=strategy)
            if not health.is_tradeable:
                return ConditionResult(
                    condition="strategy_health_gate",
                    status=ConditionStatus.FAILED,
                    score=0.0,
                    reason=f"Strategy health: {health.level} — {health.reason}",
                )
            return ConditionResult(
                condition="strategy_health_gate",
                status=ConditionStatus.PASSED,
                score=getattr(health, "score", 100.0),
                reason=f"Strategy health: {health.level}",
            )
        except Exception as exc:
            logger.debug("SmartReinvest: strategy health check skipped (%s)", exc)
            return ConditionResult(
                condition="strategy_health_gate",
                status=ConditionStatus.SKIPPED,
                score=100.0,
                reason="StrategyHealthMonitor unavailable — skipped",
            )

    def _check_win_rate(self, strategy: str) -> ConditionResult:
        try:
            try:
                from bot.win_rate_maximizer import get_win_rate_maximizer
            except ImportError:
                from win_rate_maximizer import get_win_rate_maximizer

            wmx = get_win_rate_maximizer()
            dashboard = wmx.get_dashboard()
            win_rate = dashboard.get("rolling_win_rate", None)
            if win_rate is None:
                return ConditionResult(
                    condition="win_rate_gate",
                    status=ConditionStatus.SKIPPED,
                    score=100.0,
                    reason="Insufficient trade history — win rate gate skipped",
                )
            if win_rate < self.win_rate_floor:
                return ConditionResult(
                    condition="win_rate_gate",
                    status=ConditionStatus.FAILED,
                    score=win_rate * 100.0,
                    reason=(
                        f"Rolling win rate {win_rate * 100:.1f} % "
                        f"< floor {self.win_rate_floor * 100:.1f} %"
                    ),
                )
            return ConditionResult(
                condition="win_rate_gate",
                status=ConditionStatus.PASSED,
                score=min(100.0, win_rate * 100.0),
                reason=f"Rolling win rate {win_rate * 100:.1f} % ≥ floor",
            )
        except Exception as exc:
            logger.debug("SmartReinvest: win rate check skipped (%s)", exc)
            return ConditionResult(
                condition="win_rate_gate",
                status=ConditionStatus.SKIPPED,
                score=100.0,
                reason="WinRateMaximizer unavailable — skipped",
            )

    def _check_pool(self) -> ConditionResult:
        try:
            try:
                from bot.capital_recycling_engine import get_capital_recycling_engine
            except ImportError:
                from capital_recycling_engine import get_capital_recycling_engine

            engine = get_capital_recycling_engine()
            pool_usd = engine.get_pool_balance()
            if pool_usd < self.min_pool_to_deploy:
                return ConditionResult(
                    condition="pool_gate",
                    status=ConditionStatus.FAILED,
                    score=0.0,
                    reason=(
                        f"Pool ${pool_usd:.2f} < minimum ${self.min_pool_to_deploy:.2f}"
                    ),
                )
            # Score grows with pool depth — caps at 100 after 5× minimum
            score = min(100.0, (pool_usd / self.min_pool_to_deploy) * 20.0)
            return ConditionResult(
                condition="pool_gate",
                status=ConditionStatus.PASSED,
                score=score,
                reason=f"Pool ${pool_usd:.2f} available",
            )
        except Exception as exc:
            logger.debug("SmartReinvest: pool check failed (%s)", exc)
            return ConditionResult(
                condition="pool_gate",
                status=ConditionStatus.FAILED,
                score=0.0,
                reason=f"CapitalRecyclingEngine unavailable: {exc}",
            )

    def _check_cooldown(self, strategy: str) -> ConditionResult:
        with self._lock:
            last_ts = self._state.last_deploy_ts.get(strategy)
        if last_ts is None:
            return ConditionResult(
                condition="cooldown_gate",
                status=ConditionStatus.PASSED,
                score=100.0,
                reason="No previous deployment — cooldown cleared",
            )
        elapsed = _seconds_since(last_ts)
        if elapsed < self.min_cooldown_seconds:
            remaining = self.min_cooldown_seconds - elapsed
            return ConditionResult(
                condition="cooldown_gate",
                status=ConditionStatus.FAILED,
                score=0.0,
                reason=(
                    f"Cooldown active: {remaining:.0f} s remaining "
                    f"(min {self.min_cooldown_seconds:.0f} s)"
                ),
            )
        score = min(100.0, elapsed / self.min_cooldown_seconds * 100.0)
        return ConditionResult(
            condition="cooldown_gate",
            status=ConditionStatus.PASSED,
            score=score,
            reason=f"Cooldown cleared ({elapsed:.0f} s since last deploy)",
        )

    # ── Reinvest Amount Computation ───────────────────────────────────────────

    def _compute_reinvest_amount(
        self, strategy: str, regime: str, base_position_usd: float
    ) -> float:
        """
        Compute the USD amount to reinvest, capped by ``max_reinvest_fraction``
        of the base position and ``max_reinvest_usd``, then claim it from the
        recycling engine.
        """
        cap = min(
            base_position_usd * self.max_reinvest_fraction,
            self.max_reinvest_usd,
        )
        if cap <= 0:
            return 0.0
        try:
            try:
                from bot.capital_recycling_engine import get_capital_recycling_engine
            except ImportError:
                from capital_recycling_engine import get_capital_recycling_engine

            engine = get_capital_recycling_engine()
            granted = engine.claim_allocation(
                strategy=strategy,
                requested_usd=cap,
                regime=regime,
                note="smart_reinvest_cycle",
            )
            return max(0.0, granted)
        except Exception as exc:
            logger.warning("SmartReinvest: claim_allocation failed (%s)", exc)
            return 0.0

    # ── Persistence ───────────────────────────────────────────────────────────

    def _record_deploy(self, decision: ReinvestDecision) -> None:
        """Record a successful deployment into persistent state (caller holds lock)."""
        s = self._state
        s.last_deploy_ts[decision.strategy] = decision.timestamp
        s.total_deployed[decision.strategy] = (
            s.total_deployed.get(decision.strategy, 0.0) + decision.reinvest_usd
        )
        s.total_usd_deployed += decision.reinvest_usd
        s.total_reinvest_events += 1
        event = DeployEvent(
            timestamp=decision.timestamp,
            strategy=decision.strategy,
            regime=decision.regime,
            amount_usd=decision.reinvest_usd,
            base_position_usd=decision.base_position_usd,
            readiness_score=decision.readiness_score,
        )
        s.deploy_events.append(asdict(event))
        if len(s.deploy_events) > 200:
            s.deploy_events = s.deploy_events[-200:]
        s.last_updated = _now()
        self._save_state()

    def _load_state(self) -> None:
        path = Path(self.state_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._state = ReinvestCycleState(**data)
        except Exception as exc:
            logger.warning(
                "SmartReinvest: failed to load state (%s) — resetting", exc
            )

    def _save_state(self) -> None:
        try:
            path = Path(self.state_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self._state), indent=2))
        except Exception as exc:
            logger.warning("SmartReinvest: failed to save state (%s)", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ENGINE_INSTANCE: Optional[SmartReinvestCycleEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_smart_reinvest_engine(
    state_path: str = DEFAULT_STATE_PATH,
    **kwargs,
) -> SmartReinvestCycleEngine:
    """
    Return the process-wide singleton ``SmartReinvestCycleEngine``.

    Additional keyword arguments are forwarded to the constructor only on the
    *first* call.
    """
    global _ENGINE_INSTANCE
    with _ENGINE_LOCK:
        if _ENGINE_INSTANCE is None:
            _ENGINE_INSTANCE = SmartReinvestCycleEngine(
                state_path=state_path, **kwargs
            )
    return _ENGINE_INSTANCE
