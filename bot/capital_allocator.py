"""
NIJA Capital Allocator
=======================

Cycle-oriented capital allocation layer that enforces the five-step trading
cycle defined below.  It sits between the balance-refresh step and the
execution engine so that **every trade is sized against a pre-computed,
performance-adjusted capital budget**.

Cycle flow
----------
::

    ┌─────────────────────────────────────────────────────────────┐
    │  1. Refresh balances          (broker.get_balance)          │
    │         ↓                                                   │
    │  2. CapitalAllocator.rebalance(total_capital)               │
    │         ↓                                                   │
    │  3. Strategy sizing  →  allocator.get_allocated_capital()   │
    │         ↓                                                   │
    │  4. Execution runs            (broker.place_order)          │
    │         ↓                                                   │
    │  5. Record results  →  allocator.record_result(...)         │
    └─────────────────────────────────────────────────────────────┘

Key features
------------
* **Performance-based weights** — wraps :class:`~bot.strategy_allocation_engine.StrategyAllocationEngine`
  which scores each strategy on EMA return, win-rate, profit-factor, and Sharpe.
* **Reserve capital** — a configurable fraction (default 10 %) is always held
  back from allocation so the bot retains a cash buffer.
* **Rate-limited rebalance** — full rebalance runs at most once per
  ``min_rebalance_interval_s`` seconds (default 60 s) to avoid thrashing
  weights on every cycle.  Capital-only updates (no weight recomputation)
  can be forced with ``force=True``.
* **Per-strategy budget cap** — ``get_allocated_capital(strategy)`` returns
  the USD budget available for a single trade, calculated as
  ``strategy_allocation / max_concurrent_positions``.
* **Graceful degradation** — if ``StrategyAllocationEngine`` is unavailable
  the allocator falls back to an equal-weight split of deployable capital.

Usage
-----
::

    from bot.capital_allocator import get_capital_allocator

    allocator = get_capital_allocator()

    # ── Step 2 (once per cycle, after balance refresh) ──────────
    allocations = allocator.rebalance(total_capital=1_500.0)

    # ── Step 3 (inside entry loop) ──────────────────────────────
    budget = allocator.get_allocated_capital("APEX_V71")
    position_size = min(position_size, budget)

    # ── Step 5 (after every closed trade) ───────────────────────
    allocator.record_result(
        strategy="APEX_V71",
        pnl_usd=+42.0,
        is_win=True,
        position_size_usd=position_size,
    )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.capital_allocator")

# ---------------------------------------------------------------------------
# Optional: StrategyAllocationEngine backend
# ---------------------------------------------------------------------------

try:
    from bot.strategy_allocation_engine import (
        get_strategy_allocation_engine,
        StrategyAllocationEngine,
        StrategyRecord,
        DEFAULT_STRATEGIES,
    )
    _SAE_AVAILABLE = True
except ImportError:
    try:
        from strategy_allocation_engine import (  # type: ignore
            get_strategy_allocation_engine,
            StrategyAllocationEngine,
            StrategyRecord,
            DEFAULT_STRATEGIES,
        )
        _SAE_AVAILABLE = True
    except ImportError:
        get_strategy_allocation_engine = None  # type: ignore
        StrategyAllocationEngine = None  # type: ignore
        StrategyRecord = None  # type: ignore
        DEFAULT_STRATEGIES = ["APEX_V71"]  # type: ignore
        _SAE_AVAILABLE = False
        logger.warning(
            "StrategyAllocationEngine not available — "
            "CapitalAllocator will use equal-weight fallback"
        )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fraction of total capital held back as reserve (never allocated to strategies)
DEFAULT_RESERVE_PCT: float = float(os.environ.get("CA_RESERVE_PCT", "0.10"))

# Minimum seconds between full weight-rebalances (rate limiter)
DEFAULT_MIN_REBALANCE_INTERVAL_S: float = float(
    os.environ.get("CA_REBALANCE_INTERVAL_S", "60")
)

# Maximum number of concurrent positions per strategy (used to compute per-trade budget)
DEFAULT_MAX_CONCURRENT_POSITIONS: int = int(
    os.environ.get("CA_MAX_CONCURRENT_POSITIONS", "3")
)

# State file for audit trail
_DEFAULT_DATA_DIR = Path(os.environ.get("NIJA_DATA_DIR", "data"))
_STATE_FILE = _DEFAULT_DATA_DIR / "capital_allocator_state.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AllocationSnapshot:
    """Per-cycle allocation snapshot logged after every rebalance."""

    total_capital: float
    deployable_capital: float          # total_capital × (1 − reserve_pct)
    reserve_usd: float
    allocations: Dict[str, float]      # {strategy: usd}
    weights: Dict[str, float]          # {strategy: 0.0–1.0}
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        alloc_str = ", ".join(
            f"{s}=${v:,.2f}" for s, v in self.allocations.items()
        )
        return (
            f"AllocationSnapshot("
            f"total=${self.total_capital:,.2f}, "
            f"reserve=${self.reserve_usd:,.2f}, "
            f"deployable=${self.deployable_capital:,.2f} | "
            f"{alloc_str})"
        )


# ---------------------------------------------------------------------------
# CapitalAllocator
# ---------------------------------------------------------------------------


class CapitalAllocator:
    """
    Cycle-oriented capital allocation layer for NIJA.

    Implements the five-step cycle:
    1. **Balance refresh** — caller fetches balance from broker.
    2. **Rebalance** — :meth:`rebalance` translates total capital into
       per-strategy USD budgets, honouring reserve and rate-limit rules.
    3. **Sizing** — :meth:`get_allocated_capital` caps each trade's size.
    4. **Execution** — broker submits orders (caller responsibility).
    5. **Record results** — :meth:`record_result` feeds P&L back into the
       performance engine so weights improve over time.

    Thread-safe singleton.  Obtain via :func:`get_capital_allocator`.
    """

    def __init__(
        self,
        strategies: Optional[List[str]] = None,
        reserve_pct: float = DEFAULT_RESERVE_PCT,
        min_rebalance_interval_s: float = DEFAULT_MIN_REBALANCE_INTERVAL_S,
        max_concurrent_positions: int = DEFAULT_MAX_CONCURRENT_POSITIONS,
        state_file: Optional[Path] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._reserve_pct = max(0.0, min(0.99, reserve_pct))
        self._min_rebalance_interval_s = min_rebalance_interval_s
        self._max_concurrent_positions = max(1, max_concurrent_positions)
        self._state_file = state_file or _STATE_FILE

        # Strategy list (used for equal-weight fallback)
        self._strategies: List[str] = strategies or list(DEFAULT_STRATEGIES)
        if "APEX_V71" not in self._strategies:
            self._strategies.append("APEX_V71")

        # Current allocations: {strategy: usd}
        self._allocations: Dict[str, float] = {s: 0.0 for s in self._strategies}

        # Total capital as of last rebalance
        self._total_capital: float = 0.0
        self._last_rebalance_ts: float = 0.0    # time.monotonic()
        self._rebalance_count: int = 0

        # Per-strategy result feed for audit
        self._result_feed: List[Dict[str, Any]] = []

        # Ensure data dir exists
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        # Backend engine (optional)
        self._engine: Optional[StrategyAllocationEngine] = None
        if _SAE_AVAILABLE and get_strategy_allocation_engine is not None:
            try:
                self._engine = get_strategy_allocation_engine()
                # Bootstrap: ensure all our strategies are registered in the engine
                # so they receive an equal-weight allocation on the very first rebalance
                # rather than being silently dropped (allocation = $0).
                if StrategyRecord is not None:
                    for _s in self._strategies:
                        if _s not in self._engine._records:
                            self._engine._records[_s] = StrategyRecord(name=_s)
                            logger.debug("CapitalAllocator: bootstrapped strategy '%s' in engine", _s)
                logger.info("✅ CapitalAllocator: StrategyAllocationEngine backend active")
            except Exception as exc:
                logger.warning("CapitalAllocator: engine init failed — %s", exc)

        self._load_state()

        logger.info(
            "✅ CapitalAllocator initialised | "
            "strategies=%s | reserve=%.0f%% | rebalance_interval=%.0fs | "
            "max_concurrent=%d",
            self._strategies,
            self._reserve_pct * 100,
            self._min_rebalance_interval_s,
            self._max_concurrent_positions,
        )

    # ------------------------------------------------------------------
    # Cycle Step 2 — rebalance
    # ------------------------------------------------------------------

    def rebalance(
        self,
        total_capital: float,
        force: bool = False,
    ) -> Dict[str, float]:
        """
        **Cycle step 2** — Compute per-strategy capital budgets.

        Rebalances the allocation weights at most once per
        ``min_rebalance_interval_s`` seconds unless ``force=True``.  Between
        rebalances, only the total-capital figure is updated (weights stay
        the same, but USD amounts are rescaled).

        Parameters
        ----------
        total_capital:
            Current total account equity in USD (free cash + position value).
        force:
            When ``True``, bypasses the rate-limit and always runs a full
            weight recompute.

        Returns
        -------
        Dict[str, float]
            Mapping of strategy name → allocated USD budget.
        """
        if total_capital <= 0:
            logger.debug("CapitalAllocator.rebalance: total_capital=%.2f — skipping", total_capital)
            return dict(self._allocations)

        with self._lock:
            self._total_capital = total_capital
            deployable = total_capital * (1.0 - self._reserve_pct)
            reserve_usd = total_capital - deployable

            now = time.monotonic()
            time_since_last = now - self._last_rebalance_ts
            do_full_rebalance = (
                force
                or time_since_last >= self._min_rebalance_interval_s
                or self._rebalance_count == 0
            )

            if do_full_rebalance and self._engine is not None:
                # ── Performance-based rebalance via StrategyAllocationEngine ──
                try:
                    self._engine.update_capital(deployable)
                    raw = self._engine.rebalance()
                    # Ensure every tracked strategy has a non-zero share.
                    # Strategies with no trade history get an equal-weight floor
                    # so they are never starved to $0 on the first rebalance.
                    n = max(1, len(self._strategies))
                    equal_share = 1.0 / n
                    for s in self._strategies:
                        if raw.get(s, 0.0) == 0.0:
                            raw[s] = equal_share
                    total_raw = sum(raw.values()) or 1.0
                    for strategy in self._strategies:
                        share = raw.get(strategy, equal_share)
                        self._allocations[strategy] = deployable * (share / total_raw)
                    # Add any new strategies the engine returned
                    for s, v in raw.items():
                        if s not in self._allocations:
                            self._allocations[s] = deployable * (v / total_raw)
                    self._last_rebalance_ts = now
                    self._rebalance_count += 1
                    logger.info(
                        "⚖️  CapitalAllocator: FULL rebalance #%d "
                        "(total=$%.2f, reserve=$%.2f, deployable=$%.2f)",
                        self._rebalance_count, total_capital, reserve_usd, deployable,
                    )
                except Exception as exc:
                    logger.warning(
                        "CapitalAllocator: engine rebalance error (%s) — "
                        "falling back to equal-weight", exc
                    )
                    self._equal_weight_allocate(deployable)
                    self._last_rebalance_ts = now
                    self._rebalance_count += 1

            elif do_full_rebalance:
                # ── Equal-weight fallback (no engine) ──────────────────────
                self._equal_weight_allocate(deployable)
                self._last_rebalance_ts = now
                self._rebalance_count += 1
                logger.info(
                    "⚖️  CapitalAllocator: equal-weight rebalance #%d "
                    "(total=$%.2f, deployable=$%.2f, %d strategies)",
                    self._rebalance_count, total_capital, deployable, len(self._strategies),
                )

            else:
                # ── Rescale existing weights to new capital (no weight change) ──
                old_total = sum(self._allocations.values()) or deployable
                if old_total > 0:
                    for s in self._allocations:
                        self._allocations[s] = (
                            self._allocations[s] / old_total * deployable
                        )
                logger.debug(
                    "CapitalAllocator: capital-only rescale "
                    "(next rebalance in %.0fs)",
                    self._min_rebalance_interval_s - time_since_last,
                )

            snapshot = AllocationSnapshot(
                total_capital=total_capital,
                deployable_capital=deployable,
                reserve_usd=reserve_usd,
                allocations=dict(self._allocations),
                weights=self._get_weights_unlocked(),
            )
            logger.info("📊 %s", snapshot)
            self._save_state()
            return dict(self._allocations)

    # ------------------------------------------------------------------
    # Cycle Step 3 — get per-trade budget
    # ------------------------------------------------------------------

    def get_allocated_capital(self, strategy: str) -> float:
        """
        **Cycle step 3** — Return the USD budget for a single trade.

        The budget is ``strategy_allocation ÷ max_concurrent_positions``.
        This prevents any single trade from consuming the entire strategy
        bucket (important when multiple signals fire simultaneously).

        Parameters
        ----------
        strategy:
            Strategy identifier (e.g. ``"APEX_V71"``).

        Returns
        -------
        float
            Maximum USD size for one trade.  Returns 0.0 when total capital
            has not yet been set (i.e. :meth:`rebalance` has never been called).
        """
        with self._lock:
            alloc = self._allocations.get(strategy)
            if alloc is None:
                # Unknown strategy: fall back to equal share of deployable capital
                deployable = self._total_capital * (1.0 - self._reserve_pct)
                n = max(1, len(self._strategies))
                alloc = deployable / n
            budget = alloc / self._max_concurrent_positions
            return max(0.0, budget)

    # ------------------------------------------------------------------
    # Cycle Step 5 — record trade result
    # ------------------------------------------------------------------

    def record_result(
        self,
        strategy: str,
        pnl_usd: float,
        is_win: bool,
        position_size_usd: float = 100.0,
    ) -> None:
        """
        **Cycle step 5** — Feed a closed-trade result back into the engine.

        Updates the strategy's performance score so the *next* rebalance
        will shift more capital toward better-performing strategies.

        Parameters
        ----------
        strategy:
            Strategy identifier (e.g. ``"APEX_V71"``).
        pnl_usd:
            Realised P&L in USD (+profit / −loss).
        is_win:
            ``True`` if the trade was profitable.
        position_size_usd:
            Actual trade size in USD (used for normalised-return calculation).
        """
        # Feed into the backend engine
        if self._engine is not None:
            try:
                self._engine.record_trade(
                    strategy=strategy,
                    pnl_usd=pnl_usd,
                    is_win=is_win,
                    position_size_usd=max(1.0, position_size_usd),
                )
            except Exception as exc:
                logger.warning("CapitalAllocator.record_result engine error: %s", exc)

        # Append to audit feed
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy,
            "pnl_usd": pnl_usd,
            "is_win": is_win,
            "position_size_usd": position_size_usd,
        }
        with self._lock:
            self._result_feed.append(record)
            # Trim audit buffer to last 500 records to avoid unbounded growth
            if len(self._result_feed) > 500:
                self._result_feed = self._result_feed[-500:]
            self._save_state()

        logger.info(
            "📝 CapitalAllocator: recorded %s result | "
            "strategy=%s pnl=%+.2f is_win=%s size=$%.2f",
            "WIN ✅" if is_win else "LOSS ❌",
            strategy, pnl_usd, is_win, position_size_usd,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable status report."""
        with self._lock:
            weights = self._get_weights_unlocked()
            deployable = self._total_capital * (1.0 - self._reserve_pct)
            reserve = self._total_capital - deployable
            lines = [
                "=" * 64,
                "💰  CAPITAL ALLOCATOR — STATUS REPORT",
                "=" * 64,
                f"  Total Capital         : ${self._total_capital:>12,.2f}",
                f"  Reserve ({self._reserve_pct:.0%})         : ${reserve:>12,.2f}",
                f"  Deployable Capital    : ${deployable:>12,.2f}",
                f"  Rebalances Done       : {self._rebalance_count:>12}",
                f"  Max Concurrent Pos.   : {self._max_concurrent_positions:>12}",
                "-" * 64,
                "  Strategy Allocations:",
            ]
            for s, usd in sorted(self._allocations.items()):
                per_trade = usd / self._max_concurrent_positions
                w = weights.get(s, 0.0)
                lines.append(
                    f"    {s:<22} ${usd:>10,.2f}  "
                    f"({w:.0%})  per-trade cap: ${per_trade:,.2f}"
                )
            lines.append("=" * 64)
            return "\n".join(lines)

    def get_metrics(self) -> Dict[str, Any]:
        """Return a serialisable metrics dict for APIs and dashboards."""
        with self._lock:
            weights = self._get_weights_unlocked()
            deployable = self._total_capital * (1.0 - self._reserve_pct)
            return {
                "total_capital_usd": self._total_capital,
                "reserve_usd": self._total_capital - deployable,
                "deployable_capital_usd": deployable,
                "allocations_usd": dict(self._allocations),
                "weights": weights,
                "rebalance_count": self._rebalance_count,
                "max_concurrent_positions": self._max_concurrent_positions,
                "reserve_pct": self._reserve_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _equal_weight_allocate(self, deployable: float) -> None:
        """Distribute deployable capital equally across all strategies (under lock)."""
        n = max(1, len(self._strategies))
        share = deployable / n
        for s in self._strategies:
            self._allocations[s] = share

    def _get_weights_unlocked(self) -> Dict[str, float]:
        """Return fractional weights (must be called under lock)."""
        total = sum(self._allocations.values())
        if total <= 0:
            n = max(1, len(self._allocations))
            return {s: 1.0 / n for s in self._allocations}
        return {s: v / total for s, v in self._allocations.items()}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist allocations and result feed (must be called under lock)."""
        state = {
            "total_capital": self._total_capital,
            "allocations": self._allocations,
            "rebalance_count": self._rebalance_count,
            "result_feed": self._result_feed[-100:],   # last 100 for storage efficiency
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._state_file, "w") as fh:
                json.dump(state, fh, indent=2)
        except Exception as exc:
            logger.warning("CapitalAllocator: state save failed — %s", exc)

    def _load_state(self) -> None:
        """Restore persisted state on startup."""
        try:
            with open(self._state_file, "r") as fh:
                state = json.load(fh)
            self._total_capital = float(state.get("total_capital", 0.0))
            for s, v in state.get("allocations", {}).items():
                self._allocations[s] = float(v)
            self._rebalance_count = int(state.get("rebalance_count", 0))
            self._result_feed = state.get("result_feed", [])
            logger.info(
                "💾 CapitalAllocator: state loaded "
                "(total=$%.2f, rebalances=%d)",
                self._total_capital, self._rebalance_count,
            )
        except FileNotFoundError:
            pass  # First run — start fresh
        except Exception as exc:
            logger.warning("CapitalAllocator: state load failed — %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ALLOCATOR_INSTANCE: Optional[CapitalAllocator] = None
_ALLOCATOR_INSTANCE_LOCK = threading.Lock()


def get_capital_allocator() -> CapitalAllocator:
    """
    Return the process-wide singleton :class:`CapitalAllocator`.

    Thread-safe; created once on first call.
    """
    global _ALLOCATOR_INSTANCE
    if _ALLOCATOR_INSTANCE is None:
        with _ALLOCATOR_INSTANCE_LOCK:
            if _ALLOCATOR_INSTANCE is None:
                _ALLOCATOR_INSTANCE = CapitalAllocator()
    return _ALLOCATOR_INSTANCE
