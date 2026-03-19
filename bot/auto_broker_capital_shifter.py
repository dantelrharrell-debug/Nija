"""
NIJA Auto Broker Capital Shifter
==================================

Continuously evaluates ``BrokerPerformanceScorer`` composite scores and
automatically shifts **capital allocation weights** toward the
best-performing brokers over time.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │                AutoBrokerCapitalShifter                      │
  │                                                              │
  │  1. Read live composite scores from BrokerPerformanceScorer  │
  │  2. Convert scores → target weights via softmax              │
  │  3. EMA-blend current allocations → target                   │
  │  4. Enforce per-broker min/max bounds + renormalise          │
  │  5. Apply hysteresis + cooldown (no thrashing)               │
  │  6. Persist allocations + full shift audit log               │
  └──────────────────────────────────────────────────────────────┘

Shift Policies
--------------
=====================  =========  ==========  =============
Policy                 EMA alpha  Hysteresis  Cooldown
=====================  =========  ==========  =============
``CONSERVATIVE``       0.05       5 %         600 s (10 min)
``BALANCED``           0.15       2 %         300 s (5 min)
``AGGRESSIVE``         0.30       1 %         60 s  (1 min)
=====================  =========  ==========  =============

Usage
-----
::

    from bot.auto_broker_capital_shifter import (
        get_auto_broker_capital_shifter,
        ShiftPolicy,
    )

    shifter = get_auto_broker_capital_shifter()

    # Register tracked brokers (call once at startup):
    shifter.register_broker("coinbase", initial_allocation=0.60)
    shifter.register_broker("kraken",   initial_allocation=0.30)
    shifter.register_broker("binance",  initial_allocation=0.10)

    # Evaluate and (optionally) shift allocations — call periodically:
    result = shifter.evaluate()
    if result.shifted:
        for broker, alloc in result.new_allocations.items():
            apply_capital_allocation(broker, alloc)

    # Operator override:
    shifter.force_allocation("coinbase", 0.70)

    # Dashboard:
    print(shifter.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.auto_broker_capital_shifter")

# ---------------------------------------------------------------------------
# Optional: BrokerPerformanceScorer
# ---------------------------------------------------------------------------

try:
    from bot.broker_performance_scorer import get_broker_performance_scorer
    _BPS_AVAILABLE = True
except ImportError:
    try:
        from broker_performance_scorer import get_broker_performance_scorer
        _BPS_AVAILABLE = True
    except ImportError:
        _BPS_AVAILABLE = False
        get_broker_performance_scorer = None  # type: ignore
        logger.warning(
            "⚠️  BrokerPerformanceScorer not available — "
            "capital shifter will hold equal allocations"
        )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Softmax temperature: higher → more uniform allocations (less aggressive shift)
DEFAULT_SOFTMAX_TEMPERATURE: float = 20.0

# Default per-broker bounds if not overridden
DEFAULT_MIN_ALLOCATION: float = 0.05
DEFAULT_MAX_ALLOCATION: float = 0.80

# Maximum entries in the shift audit log kept in memory
MAX_SHIFT_LOG: int = 200


# ---------------------------------------------------------------------------
# Enums / data classes
# ---------------------------------------------------------------------------


class ShiftPolicy(str, Enum):
    """Controls how aggressively capital allocations respond to score changes."""
    CONSERVATIVE = "conservative"   # slow drift
    BALANCED     = "balanced"       # moderate response (default)
    AGGRESSIVE   = "aggressive"     # fast response


#: Policy parameters: (ema_alpha, hysteresis_pct, cooldown_seconds)
_POLICY_PARAMS: Dict[ShiftPolicy, Tuple[float, float, int]] = {
    ShiftPolicy.CONSERVATIVE: (0.05, 0.05, 600),
    ShiftPolicy.BALANCED:     (0.15, 0.02, 300),
    ShiftPolicy.AGGRESSIVE:   (0.30, 0.01, 60),
}


@dataclass(frozen=True)
class BrokerBounds:
    """Per-broker allocation constraints."""
    min_allocation: float = DEFAULT_MIN_ALLOCATION
    max_allocation: float = DEFAULT_MAX_ALLOCATION


@dataclass
class ShiftResult:
    """Result of a single ``evaluate()`` call."""
    evaluated_at: str
    shifted: bool
    brokers_evaluated: List[str]
    old_allocations: Dict[str, float]
    new_allocations: Dict[str, float]
    score_snapshot: Dict[str, float]   # broker → composite_score at evaluation time
    reason: str
    blocked_by: str = ""               # "cooldown" | "hysteresis" | ""


# ---------------------------------------------------------------------------
# AutoBrokerCapitalShifter
# ---------------------------------------------------------------------------


class AutoBrokerCapitalShifter:
    """
    Monitors broker performance scores and automatically shifts capital
    allocation weights toward top-performing brokers.

    Thread-safe.  State is persisted to ``data/broker_capital_allocations.json``
    so allocations survive restarts.

    Parameters
    ----------
    policy:
        :class:`ShiftPolicy` that governs EMA alpha, hysteresis, and cooldown.
    softmax_temperature:
        Temperature for the softmax transformation applied to broker scores.
        Higher values produce more uniform (conservative) target allocations.
    """

    DATA_DIR  = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "broker_capital_allocations.json"

    def __init__(
        self,
        policy: ShiftPolicy = ShiftPolicy.BALANCED,
        softmax_temperature: float = DEFAULT_SOFTMAX_TEMPERATURE,
    ) -> None:
        self._lock = threading.RLock()

        self._policy = policy
        self._temperature = softmax_temperature

        ema_alpha, hysteresis, cooldown = _POLICY_PARAMS[policy]
        self._ema_alpha: float   = ema_alpha
        self._hysteresis: float  = hysteresis   # minimum absolute shift per broker
        self._cooldown_s: int    = cooldown      # seconds between shifts

        # broker name → current allocation (0–1, sums to 1.0 across all brokers)
        self._allocations: Dict[str, float] = {}
        # broker name → bounds
        self._bounds: Dict[str, BrokerBounds] = {}

        self._last_shift_ts: Optional[float] = None
        self._shift_log: List[Dict] = []

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info("=" * 70)
        logger.info("🔀 AutoBrokerCapitalShifter initialised")
        logger.info(
            "   policy=%s  alpha=%.2f  hysteresis=%.0f%%  cooldown=%ds",
            policy.value, ema_alpha, hysteresis * 100, cooldown,
        )
        logger.info(
            "   softmax_temperature=%.1f  brokers_loaded=%d",
            softmax_temperature, len(self._allocations),
        )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API — setup
    # ------------------------------------------------------------------

    def register_broker(
        self,
        broker: str,
        initial_allocation: float = 0.0,
        min_allocation: float = DEFAULT_MIN_ALLOCATION,
        max_allocation: float = DEFAULT_MAX_ALLOCATION,
    ) -> None:
        """
        Register a broker for capital-shift tracking.

        If the broker is already registered (e.g. loaded from persisted state),
        its current allocation is preserved and only its bounds are updated.

        Parameters
        ----------
        broker:
            Broker name, e.g. ``"coinbase"``.
        initial_allocation:
            Starting capital fraction (0–1).  Ignored when state is restored
            from disk.
        min_allocation:
            Absolute floor for this broker's capital share.
        max_allocation:
            Absolute ceiling for this broker's capital share.
        """
        if not (0.0 <= min_allocation <= max_allocation <= 1.0):
            raise ValueError(
                f"Invalid bounds for {broker!r}: "
                f"min={min_allocation}, max={max_allocation}"
            )
        if not (0.0 <= initial_allocation <= 1.0):
            raise ValueError(
                f"initial_allocation must be in [0, 1], got {initial_allocation}"
            )

        with self._lock:
            self._bounds[broker] = BrokerBounds(
                min_allocation=min_allocation,
                max_allocation=max_allocation,
            )
            if broker not in self._allocations:
                self._allocations[broker] = initial_allocation
                logger.info(
                    "📌 Registered broker %r  alloc=%.1f%%  bounds=[%.1f%%, %.1f%%]",
                    broker, initial_allocation * 100,
                    min_allocation * 100, max_allocation * 100,
                )
            else:
                logger.info(
                    "📌 Updated bounds for %r  current_alloc=%.1f%%  "
                    "bounds=[%.1f%%, %.1f%%]",
                    broker, self._allocations[broker] * 100,
                    min_allocation * 100, max_allocation * 100,
                )

    # ------------------------------------------------------------------
    # Public API — evaluation
    # ------------------------------------------------------------------

    def evaluate(self) -> ShiftResult:
        """
        Evaluate broker scores and compute (possibly apply) a new allocation.

        This is the main call site.  Invoke it periodically (e.g. every
        ``cooldown_seconds`` or whenever a batch of orders completes).

        Returns
        -------
        :class:`ShiftResult` describing what happened (and whether any
        shift was actually applied).
        """
        now_ts = datetime.now(timezone.utc).timestamp()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            brokers = list(self._allocations.keys())
            old_allocs = dict(self._allocations)

        if not brokers:
            return ShiftResult(
                evaluated_at=now_iso,
                shifted=False,
                brokers_evaluated=[],
                old_allocations={},
                new_allocations={},
                score_snapshot={},
                reason="No brokers registered",
            )

        # 1. Cooldown check
        if self._last_shift_ts is not None:
            elapsed = now_ts - self._last_shift_ts
            if elapsed < self._cooldown_s:
                remaining = int(self._cooldown_s - elapsed)
                return ShiftResult(
                    evaluated_at=now_iso,
                    shifted=False,
                    brokers_evaluated=brokers,
                    old_allocations=old_allocs,
                    new_allocations=old_allocs,
                    score_snapshot={},
                    reason=f"Cooldown active — {remaining}s remaining",
                    blocked_by="cooldown",
                )

        # 2. Fetch live scores
        scores = self._fetch_scores(brokers)

        # 3. Compute softmax-weighted target allocations
        target = self._compute_target_allocations(brokers, scores)

        # 4. EMA-blend current → target
        with self._lock:
            blended = {
                b: self._allocations[b] * (1.0 - self._ema_alpha)
                   + target[b] * self._ema_alpha
                for b in brokers
            }

        # 5. Enforce bounds + renormalise
        bounded = self._enforce_bounds(brokers, blended)

        # 6. Hysteresis check: is the max absolute change large enough?
        max_delta = max(abs(bounded[b] - old_allocs[b]) for b in brokers)
        if max_delta < self._hysteresis:
            return ShiftResult(
                evaluated_at=now_iso,
                shifted=False,
                brokers_evaluated=brokers,
                old_allocations=old_allocs,
                new_allocations=old_allocs,
                score_snapshot=scores,
                reason=(
                    f"Max allocation change ({max_delta * 100:.2f}%) "
                    f"below hysteresis threshold ({self._hysteresis * 100:.0f}%) "
                    "— no shift applied"
                ),
                blocked_by="hysteresis",
            )

        # 7. Apply the shift
        with self._lock:
            self._allocations = bounded
            self._last_shift_ts = now_ts

        reason = self._build_shift_reason(brokers, old_allocs, bounded, scores)
        result = ShiftResult(
            evaluated_at=now_iso,
            shifted=True,
            brokers_evaluated=brokers,
            old_allocations=old_allocs,
            new_allocations=dict(bounded),
            score_snapshot=scores,
            reason=reason,
        )

        self._record_shift(result)
        self._save_state()

        logger.info("🔀 Capital shift applied — %s", reason)
        for broker in sorted(brokers):
            delta = bounded[broker] - old_allocs.get(broker, 0.0)
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
            logger.info(
                "   %s %-20s  %.1f%% → %.1f%%  (%s%.2f%%)",
                arrow, broker,
                old_allocs.get(broker, 0) * 100,
                bounded[broker] * 100,
                "+" if delta >= 0 else "",
                delta * 100,
            )

        return result

    def force_allocation(self, broker: str, allocation: float) -> None:
        """
        Operator override: set the capital allocation for *broker* directly.

        Immediately updates the allocation and resets the cooldown timer so
        the next ``evaluate()`` call runs a fresh assessment.

        Parameters
        ----------
        broker:
            Broker name that must already be registered.
        allocation:
            New allocation fraction (0–1).
        """
        if broker not in self._allocations:
            raise KeyError(f"Broker {broker!r} is not registered")
        if not (0.0 <= allocation <= 1.0):
            raise ValueError(f"allocation must be in [0, 1], got {allocation}")

        with self._lock:
            old = self._allocations[broker]
            self._allocations[broker] = allocation
            self._last_shift_ts = None   # reset cooldown

        logger.info(
            "⚙️  Force allocation: %s  %.1f%% → %.1f%%",
            broker, old * 100, allocation * 100,
        )
        self._save_state()

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    def get_allocations(self) -> Dict[str, float]:
        """Return a copy of the current broker allocations."""
        with self._lock:
            return dict(self._allocations)

    def get_shift_log(self, n: int = 20) -> List[Dict]:
        """Return the *n* most recent shift records."""
        with self._lock:
            return list(self._shift_log[-n:])

    def get_report(self) -> str:
        """Return a human-readable allocation + scoring table."""
        with self._lock:
            allocs = dict(self._allocations)
            brokers = sorted(allocs.keys())

        scores = self._fetch_scores(brokers)

        lines = [
            "=" * 70,
            "  NIJA AUTO BROKER CAPITAL SHIFTER — CURRENT ALLOCATIONS",
            "=" * 70,
            f"  {'Broker':<30}  {'Alloc':>7}  {'Score':>6}  {'Min':>5}  {'Max':>5}",
            "-" * 70,
        ]
        for b in brokers:
            bounds = self._bounds.get(b, BrokerBounds())
            lines.append(
                f"  {b:<30}  {allocs[b] * 100:>6.1f}%"
                f"  {scores.get(b, 50.0):>5.1f}"
                f"  {bounds.min_allocation * 100:>4.0f}%"
                f"  {bounds.max_allocation * 100:>4.0f}%"
            )
        total = sum(allocs.values())
        lines.append("-" * 70)
        lines.append(f"  {'TOTAL':<30}  {total * 100:>6.1f}%")
        lines.append(f"  Policy: {self._policy.value}  |  "
                     f"EMA alpha: {self._ema_alpha}  |  "
                     f"Hysteresis: {self._hysteresis * 100:.0f}%  |  "
                     f"Cooldown: {self._cooldown_s}s")

        if self._shift_log:
            last = self._shift_log[-1]
            lines.append(f"  Last shift: {last.get('evaluated_at', 'n/a')}")
        lines.append("=" * 70)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_scores(self, brokers: List[str]) -> Dict[str, float]:
        """Fetch current composite scores for the given broker list."""
        scores: Dict[str, float] = {}
        if _BPS_AVAILABLE:
            try:
                scorer = get_broker_performance_scorer()
                for b in brokers:
                    scores[b] = scorer.get_score(b)
                return scores
            except Exception as exc:
                logger.warning("⚠️  Failed to fetch broker scores: %s", exc)
        # Fallback: equal scores
        for b in brokers:
            scores[b] = 50.0
        return scores

    def _compute_target_allocations(
        self,
        brokers: List[str],
        scores: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Convert broker scores into target capital weights via softmax.

        A higher ``softmax_temperature`` makes the output more uniform
        (less sensitive to small score differences).
        """
        raw = [scores.get(b, 50.0) / self._temperature for b in brokers]

        # Numerically stable softmax
        max_val = max(raw)
        exp_vals = [math.exp(v - max_val) for v in raw]
        total = sum(exp_vals)

        return {b: exp_vals[i] / total for i, b in enumerate(brokers)}

    def _enforce_bounds(
        self,
        brokers: List[str],
        allocs: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Project broker allocations onto the feasible polytope defined by per-broker
        [min, max] bounds, keeping the sum equal to 1.

        Uses two alternating passes per iteration:
          1. Cap any broker over its max and redistribute the surplus to uncapped brokers.
          2. Floor any broker under its min and take the deficit from unaffected brokers.
        Repeats until convergence (max 50 iterations).
        """
        if not brokers:
            return {}

        result = dict(allocs)

        for _ in range(50):
            # Normalise to sum = 1
            total = sum(result.values())
            if total <= 0.0:
                for b in brokers:
                    result[b] = 1.0 / len(brokers)
                break
            for b in brokers:
                result[b] /= total

            # ── Pass A: handle max-cap violations ────────────────────
            over_max = [b for b in brokers
                        if result[b] > self._bounds.get(b, BrokerBounds()).max_allocation + 1e-9]
            if over_max:
                for b in over_max:
                    result[b] = self._bounds.get(b, BrokerBounds()).max_allocation
                free = [b for b in brokers if b not in over_max]
                if free:
                    cap_sum  = sum(result[b] for b in over_max)
                    remaining = 1.0 - cap_sum
                    free_sum = sum(result[b] for b in free)
                    if free_sum > 0:
                        for b in free:
                            result[b] = result[b] / free_sum * remaining
                    else:
                        share = remaining / len(free)
                        for b in free:
                            result[b] = share
                continue   # re-check after redistribution

            # ── Pass B: handle min-floor violations ──────────────────
            under_min = [b for b in brokers
                         if result[b] < self._bounds.get(b, BrokerBounds()).min_allocation - 1e-9]
            if under_min:
                for b in under_min:
                    result[b] = self._bounds.get(b, BrokerBounds()).min_allocation
                free = [b for b in brokers if b not in under_min]
                if free:
                    floor_sum = sum(result[b] for b in under_min)
                    remaining  = 1.0 - floor_sum
                    free_sum   = sum(result[b] for b in free)
                    if free_sum > 0:
                        for b in free:
                            result[b] = result[b] / free_sum * remaining
                    else:
                        share = remaining / len(free)
                        for b in free:
                            result[b] = share
                continue   # re-check after redistribution

            # No violations — done
            break

        return result

    @staticmethod
    def _build_shift_reason(
        brokers: List[str],
        old: Dict[str, float],
        new: Dict[str, float],
        scores: Dict[str, float],
    ) -> str:
        top = max(scores, key=lambda k: scores.get(k, 0.0))
        bot = min(scores, key=lambda k: scores.get(k, 0.0))
        delta_top = (new[top] - old.get(top, 0.0)) * 100
        return (
            f"top={top}(score={scores.get(top, 0.0):.1f}, "
            f"alloc {old.get(top, 0)*100:.1f}%→{new[top]*100:.1f}%, "
            f"{delta_top:+.1f}pp); "
            f"bot={bot}(score={scores.get(bot, 0.0):.1f})"
        )

    def _record_shift(self, result: ShiftResult) -> None:
        """Append a shift result to the in-memory audit log (bounded)."""
        with self._lock:
            self._shift_log.append({
                "evaluated_at": result.evaluated_at,
                "shifted": result.shifted,
                "old_allocations": result.old_allocations,
                "new_allocations": result.new_allocations,
                "score_snapshot": result.score_snapshot,
                "reason": result.reason,
            })
            if len(self._shift_log) > MAX_SHIFT_LOG:
                self._shift_log = self._shift_log[-MAX_SHIFT_LOG:]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist allocations and bounds to disk."""
        try:
            data = {
                "policy": self._policy.value,
                "last_shift_ts": self._last_shift_ts,
                "allocations": self._allocations,
                "bounds": {
                    b: {"min": v.min_allocation, "max": v.max_allocation}
                    for b, v in self._bounds.items()
                },
                "shift_log": self._shift_log[-50:],  # keep last 50 on disk
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save capital shifter state: %s", exc)

    def _load_state(self) -> None:
        """Restore persisted allocations from disk (called once at init)."""
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE) as fh:
                data = json.load(fh)

            self._allocations = {
                str(k): float(v)
                for k, v in data.get("allocations", {}).items()
            }
            for b, bnd in data.get("bounds", {}).items():
                self._bounds[str(b)] = BrokerBounds(
                    min_allocation=float(bnd.get("min", DEFAULT_MIN_ALLOCATION)),
                    max_allocation=float(bnd.get("max", DEFAULT_MAX_ALLOCATION)),
                )
            self._last_shift_ts = data.get("last_shift_ts")
            self._shift_log = data.get("shift_log", [])
            logger.info(
                "✅ Capital shifter state restored: %d brokers from %s",
                len(self._allocations), self.STATE_FILE,
            )
        except Exception as exc:
            logger.warning("Failed to load capital shifter state: %s — starting fresh", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[AutoBrokerCapitalShifter] = None
_instance_lock = threading.Lock()


def get_auto_broker_capital_shifter(
    policy: ShiftPolicy = ShiftPolicy.BALANCED,
    **kwargs,
) -> AutoBrokerCapitalShifter:
    """
    Return the process-wide :class:`AutoBrokerCapitalShifter` singleton.

    Parameters are forwarded to the constructor on the *first* call only.
    Subsequent calls always return the same instance regardless of arguments.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AutoBrokerCapitalShifter(policy=policy, **kwargs)
    return _instance


__all__ = [
    "ShiftPolicy",
    "BrokerBounds",
    "ShiftResult",
    "AutoBrokerCapitalShifter",
    "get_auto_broker_capital_shifter",
]


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random
    import time as _time

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if _BPS_AVAILABLE:
        scorer = get_broker_performance_scorer()
        random.seed(99)
        for _ in range(30):
            for bname, fill_p, lat_mu in [
                ("coinbase", 0.97, 75),
                ("kraken",   0.88, 130),
                ("binance",  0.80, 210),
            ]:
                ok = random.random() < fill_p
                scorer.record_order_result(
                    bname, ok,
                    latency_ms=max(0, random.gauss(lat_mu, 20)),
                    slippage_bps=random.uniform(0.5, 3.0),
                )

    shifter = AutoBrokerCapitalShifter(policy=ShiftPolicy.AGGRESSIVE)
    shifter.register_broker("coinbase", 0.60)
    shifter.register_broker("kraken",   0.30)
    shifter.register_broker("binance",  0.10, min_allocation=0.05)

    print("\n--- Before evaluate ---")
    print(shifter.get_report())

    result = shifter.evaluate()
    print(f"\nShifted: {result.shifted}")
    print(f"Reason:  {result.reason}")

    print("\n--- After evaluate ---")
    print(shifter.get_report())
    print("\n✅ Smoke-test complete.")
