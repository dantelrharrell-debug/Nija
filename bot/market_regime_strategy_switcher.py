"""
NIJA Market Regime Strategy Switcher
=====================================

Real-time orchestrator that monitors the detected market regime and
switches the active trading strategy accordingly.  The switcher sits
above the existing :class:`StrategyManager` and adds:

* **Hysteresis** – a regime must persist for ``min_bars_before_switch``
  consecutive bars before an actual strategy switch is triggered.
* **Cooldown guard** – after a switch the switcher is locked for
  ``cooldown_bars`` bars to prevent thrashing.
* **Performance-based veto** – if the incoming strategy underperformed
  its minimum win-rate threshold over the last ``perf_lookback`` trades
  in the current regime, the switch is deferred.
* **Transition log** – a bounded deque of every switch event for
  audit / analytics.

Architecture
------------
::

    Market Scan (each bar)
          │
          ▼
    ┌─────────────────────────────────────────────────────────┐
    │              MarketRegimeStrategySwitcher               │
    │                                                         │
    │  update(regime, confidence, df, indicators)             │
    │    1. _should_switch(regime, confidence) → bool          │
    │       • hysteresis counter                              │
    │       • cooldown guard                                  │
    │       • confidence threshold                            │
    │    2. _performance_veto(incoming_regime) → bool         │
    │       • min win-rate check                              │
    │    3. _execute_switch(new_regime)                       │
    │       • StrategyManager.select_strategy()               │
    │       • log transition                                  │
    │    4. return active strategy signal                     │
    └─────────────────────────────────────────────────────────┘

Public API
----------
::

    from bot.market_regime_strategy_switcher import get_market_regime_strategy_switcher

    switcher = get_market_regime_strategy_switcher()

    # Each bar:
    result = switcher.update(
        regime="RANGING",
        confidence=0.82,
        df=ohlcv_df,
        indicators=computed_indicators,
    )
    signal     = result["signal"]
    switched   = result["switched"]
    active_str = result["active_strategy"]

    # After a trade closes:
    switcher.record_trade_result(regime="RANGING", pnl_pct=1.4, is_win=True)

    # Introspection:
    summary = switcher.get_summary()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.market_regime_strategy_switcher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_BARS_BEFORE_SWITCH: int = 3        # bars a new regime must persist
COOLDOWN_BARS: int = 5                 # bars to lock after a switch
CONFIDENCE_THRESHOLD: float = 0.55    # minimum confidence to accept new regime
MIN_WIN_RATE_VETO: float = 0.30       # veto switch if strategy WR < this value
PERF_LOOKBACK: int = 20               # recent trades to check for performance veto
MIN_TRADES_FOR_VETO: int = 10         # minimum trades in regime before veto activates
TRANSITION_LOG_MAX: int = 200         # max stored transition events


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TransitionEvent:
    """Records a single regime → strategy switch."""
    timestamp: str
    from_regime: Optional[str]
    to_regime: str
    from_strategy: Optional[str]
    to_strategy: str
    confidence: float
    bars_in_regime: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "from_regime": self.from_regime,
            "to_regime": self.to_regime,
            "from_strategy": self.from_strategy,
            "to_strategy": self.to_strategy,
            "confidence": round(self.confidence, 4),
            "bars_in_regime": self.bars_in_regime,
            "reason": self.reason,
        }


@dataclass
class RegimePerformanceTracker:
    """Lightweight rolling win-rate tracker per regime."""
    regime: str
    results: List[float] = field(default_factory=list)   # pnl_pct per trade
    wins: int = 0
    trades: int = 0

    def record(self, pnl_pct: float, is_win: bool) -> None:
        self.trades += 1
        if is_win:
            self.wins += 1
        self.results.append(pnl_pct)
        if len(self.results) > PERF_LOOKBACK:
            self.results = self.results[-PERF_LOOKBACK:]

    def recent_win_rate(self, lookback: int = PERF_LOOKBACK) -> float:
        recent = self.results[-lookback:] if len(self.results) >= lookback else self.results
        if not recent:
            return 0.5   # neutral – no data, don't bias either way
        return sum(1 for p in recent if p > 0) / len(recent)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": round(self.wins / self.trades, 4) if self.trades else 0.0,
            "recent_win_rate": round(self.recent_win_rate(), 4),
        }


# ---------------------------------------------------------------------------
# MarketRegimeStrategySwitcher
# ---------------------------------------------------------------------------

class MarketRegimeStrategySwitcher:
    """
    Real-time market regime → strategy orchestrator.

    The switcher wraps a :class:`~bot.strategy_manager.StrategyManager`
    and decides *when* to switch the active strategy, not just *which*
    strategy to use.  This prevents noisy regime detectors from causing
    constant strategy churn.
    """

    def __init__(
        self,
        min_bars_before_switch: int = MIN_BARS_BEFORE_SWITCH,
        cooldown_bars: int = COOLDOWN_BARS,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        min_win_rate_veto: float = MIN_WIN_RATE_VETO,
        perf_lookback: int = PERF_LOOKBACK,
    ) -> None:
        # Hysteresis + cooldown params
        self.min_bars = min_bars_before_switch
        self.cooldown_bars = cooldown_bars
        self.confidence_threshold = confidence_threshold
        self.min_win_rate_veto = min_win_rate_veto
        self.perf_lookback = perf_lookback

        # Internal state
        self._active_regime: Optional[str] = None
        self._pending_regime: Optional[str] = None
        self._pending_bars: int = 0
        self._cooldown_remaining: int = 0
        self._total_switches: int = 0
        self._bars_in_regime: int = 0

        # Per-regime performance trackers
        self._perf: Dict[str, RegimePerformanceTracker] = {}

        # Transition log
        self._transitions: deque = deque(maxlen=TRANSITION_LOG_MAX)

        # Lazy import of StrategyManager to avoid circular imports
        self._strategy_manager = None
        self._lock = threading.Lock()

        logger.info(
            "🔄 MarketRegimeStrategySwitcher initialised | "
            "min_bars=%d cooldown=%d confidence_threshold=%.2f",
            self.min_bars,
            self.cooldown_bars,
            self.confidence_threshold,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_strategy_manager(self):
        if self._strategy_manager is None:
            try:
                from bot.strategy_manager import StrategyManager
            except ImportError:
                from strategy_manager import StrategyManager
            self._strategy_manager = StrategyManager()
        return self._strategy_manager

    def _get_perf(self, regime: str) -> RegimePerformanceTracker:
        if regime not in self._perf:
            self._perf[regime] = RegimePerformanceTracker(regime=regime)
        return self._perf[regime]

    def _should_switch(self, new_regime: str, confidence: float) -> bool:
        """Decide whether a switch should be initiated."""
        if confidence < self.confidence_threshold:
            logger.debug(
                "Switch to '%s' suppressed: confidence %.3f < %.3f",
                new_regime,
                confidence,
                self.confidence_threshold,
            )
            return False

        if self._cooldown_remaining > 0:
            logger.debug(
                "Switch to '%s' suppressed: cooldown %d bars remaining",
                new_regime,
                self._cooldown_remaining,
            )
            return False

        if new_regime == self._active_regime:
            return False

        # Hysteresis: require consistent new regime for min_bars
        if new_regime == self._pending_regime:
            self._pending_bars += 1
        else:
            self._pending_regime = new_regime
            self._pending_bars = 1

        if self._pending_bars >= self.min_bars:
            return True

        logger.debug(
            "Switch to '%s' pending: %d/%d bars",
            new_regime,
            self._pending_bars,
            self.min_bars,
        )
        return False

    def _performance_veto(self, incoming_regime: str) -> bool:
        """
        Return True if the switch should be vetoed due to poor recent
        performance of the strategy assigned to ``incoming_regime``.
        """
        perf = self._get_perf(incoming_regime)
        if perf.trades < MIN_TRADES_FOR_VETO:
            # Not enough data → allow the switch
            return False
        wr = perf.recent_win_rate(self.perf_lookback)
        if wr < self.min_win_rate_veto:
            logger.warning(
                "⛔ Performance veto for regime '%s': recent WR=%.2f < %.2f",
                incoming_regime,
                wr,
                self.min_win_rate_veto,
            )
            return True
        return False

    def _execute_switch(
        self, new_regime: str, confidence: float, reason: str = "hysteresis_passed"
    ) -> str:
        """Switch active strategy to match new_regime; returns new strategy name."""
        mgr = self._get_strategy_manager()
        strategy = mgr.select_strategy(new_regime)
        new_strategy_name = strategy.name

        from_strategy = None
        if self._active_regime:
            old_strategy = mgr.select_strategy(self._active_regime)
            from_strategy = old_strategy.name

        event = TransitionEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_regime=self._active_regime,
            to_regime=new_regime,
            from_strategy=from_strategy,
            to_strategy=new_strategy_name,
            confidence=confidence,
            bars_in_regime=self._bars_in_regime,
            reason=reason,
        )
        self._transitions.append(event)
        self._total_switches += 1

        logger.info(
            "🔄 Strategy switch #%d: regime '%s' → '%s' | strategy '%s' → '%s' "
            "| confidence=%.3f reason=%s",
            self._total_switches,
            self._active_regime,
            new_regime,
            from_strategy,
            new_strategy_name,
            confidence,
            reason,
        )

        self._active_regime = new_regime
        self._pending_regime = None
        self._pending_bars = 0
        self._cooldown_remaining = self.cooldown_bars
        self._bars_in_regime = 0

        return new_strategy_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        regime: str,
        confidence: float,
        df=None,
        indicators: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Process one bar tick.

        Args:
            regime:      Detected market regime string (e.g. ``"TRENDING"``).
            confidence:  Classifier confidence score (0–1).
            df:          OHLCV DataFrame (forwarded to strategy).
            indicators:  Pre-computed indicator dict (forwarded to strategy).

        Returns:
            Dict with keys:

            * ``signal``          – strategy signal dict (or ``{}`` if no df).
            * ``active_regime``   – currently active regime string.
            * ``active_strategy`` – name of the strategy being used.
            * ``switched``        – True if a switch occurred this bar.
            * ``cooldown_remaining`` – bars before next switch is allowed.
        """
        with self._lock:
            indicators = indicators or {}
            switched = False

            # Decrement cooldown
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= 1

            # Bootstrap: first call
            if self._active_regime is None:
                self._execute_switch(regime, confidence, reason="bootstrap")
                self._bars_in_regime = 1   # count this bar in the new regime
                switched = True

            elif self._should_switch(regime, confidence):
                if not self._performance_veto(regime):
                    self._execute_switch(regime, confidence)
                    switched = True
                else:
                    # Veto: stay on current regime but still tick the bar
                    self._bars_in_regime += 1
            else:
                self._bars_in_regime += 1

            # Generate signal from active strategy
            mgr = self._get_strategy_manager()
            signal: Dict[str, Any] = {}
            if df is not None:
                signal = mgr.get_signal(self._active_regime, df, indicators)

            active_strategy_name = mgr.select_strategy(self._active_regime).name

        return {
            "signal": signal,
            "active_regime": self._active_regime,
            "active_strategy": active_strategy_name,
            "switched": switched,
            "cooldown_remaining": self._cooldown_remaining,
        }

    def record_trade_result(
        self,
        regime: str,
        pnl_pct: float,
        is_win: bool,
    ) -> None:
        """
        Record a completed trade result for performance-veto tracking.

        Args:
            regime:   Regime under which the trade was taken.
            pnl_pct:  Percentage P&L of the trade.
            is_win:   Whether the trade was a win.
        """
        with self._lock:
            self._get_perf(regime).record(pnl_pct, is_win)

    def force_switch(self, regime: str, reason: str = "operator_override") -> str:
        """
        Immediately switch to a given regime, bypassing hysteresis and cooldown.

        Args:
            regime: Target regime string.
            reason: Human-readable reason for audit log.

        Returns:
            Name of the newly activated strategy.
        """
        with self._lock:
            self._cooldown_remaining = 0
            self._pending_bars = self.min_bars
            return self._execute_switch(regime, confidence=1.0, reason=reason)

    def get_summary(self) -> Dict[str, Any]:
        """Return a diagnostics snapshot for dashboards / logging."""
        with self._lock:
            mgr = self._get_strategy_manager()
            active_strategy = (
                mgr.select_strategy(self._active_regime).name
                if self._active_regime
                else None
            )
            return {
                "active_regime": self._active_regime,
                "active_strategy": active_strategy,
                "total_switches": self._total_switches,
                "bars_in_current_regime": self._bars_in_regime,
                "cooldown_remaining": self._cooldown_remaining,
                "pending_regime": self._pending_regime,
                "pending_bars": self._pending_bars,
                "performance_per_regime": {
                    r: p.to_dict() for r, p in self._perf.items()
                },
                "recent_transitions": [
                    e.to_dict() for e in list(self._transitions)[-10:]
                ],
            }

    def get_transition_log(self) -> List[Dict[str, Any]]:
        """Return the full transition log."""
        with self._lock:
            return [e.to_dict() for e in self._transitions]


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_switcher_instance: Optional[MarketRegimeStrategySwitcher] = None
_switcher_lock = threading.Lock()


def get_market_regime_strategy_switcher(
    min_bars_before_switch: int = MIN_BARS_BEFORE_SWITCH,
    cooldown_bars: int = COOLDOWN_BARS,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    min_win_rate_veto: float = MIN_WIN_RATE_VETO,
) -> MarketRegimeStrategySwitcher:
    """Return the process-level singleton MarketRegimeStrategySwitcher."""
    global _switcher_instance
    if _switcher_instance is None:
        with _switcher_lock:
            if _switcher_instance is None:
                _switcher_instance = MarketRegimeStrategySwitcher(
                    min_bars_before_switch=min_bars_before_switch,
                    cooldown_bars=cooldown_bars,
                    confidence_threshold=confidence_threshold,
                    min_win_rate_veto=min_win_rate_veto,
                )
    return _switcher_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import random
    import sys
    import types

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    # ── Lightweight mock strategy so the self-test works without the full
    #    dependency stack (coinbase, pandas, etc.)  ──────────────────────
    class _MockStrategy:
        def __init__(self, name: str) -> None:
            self.name = name

        def on_regime_change(self, regime: str) -> None:
            pass

        def generate_signal(self, df, indicators):  # type: ignore[override]
            return {"action": "HOLD"}

        def get_parameters(self):
            return {}

    class _MockStrategyManager:
        _REGIME_MAP = {
            "TRENDING": "ApexTrendStrategy",
            "RANGING":  "MeanReversionStrategy",
            "VOLATILE": "MomentumBreakoutStrategy",
        }

        def select_strategy(self, regime: str) -> _MockStrategy:
            return _MockStrategy(self._REGIME_MAP.get(regime.upper(), "ApexTrendStrategy"))

        def get_signal(self, regime: str, df, indicators) -> dict:  # type: ignore[override]
            return {"action": "HOLD", "strategy": self.select_strategy(regime).name}

    # Monkey-patch the lazy import so no real deps are needed
    _sm_mod = types.ModuleType("strategy_manager")
    _sm_mod.StrategyManager = _MockStrategyManager  # type: ignore[attr-defined]
    sys.modules.setdefault("strategy_manager", _sm_mod)
    sys.modules.setdefault("bot.strategy_manager", _sm_mod)

    # ── Run the switcher scenario ─────────────────────────────────────────
    switcher = MarketRegimeStrategySwitcher(
        min_bars_before_switch=2,
        cooldown_bars=3,
        confidence_threshold=0.55,
    )

    scenarios = [
        ("TRENDING", 0.80),
        ("TRENDING", 0.82),
        ("TRENDING", 0.79),
        ("RANGING",  0.70),
        ("RANGING",  0.71),
        ("RANGING",  0.72),
        ("VOLATILE", 0.90),
        ("VOLATILE", 0.91),
        ("VOLATILE", 0.88),
        ("TRENDING", 0.85),
    ]

    for i, (regime, conf) in enumerate(scenarios, 1):
        result = switcher.update(regime=regime, confidence=conf)
        switcher.record_trade_result(
            regime=result["active_regime"],
            pnl_pct=random.gauss(0.5, 1.0),
            is_win=random.random() > 0.4,
        )
        print(
            f"Bar {i:2d} | detected={regime:<10} conf={conf:.2f} | "
            f"active={result['active_regime']:<10} strategy={result['active_strategy']:<28} "
            f"switched={result['switched']} cooldown={result['cooldown_remaining']}"
        )

    print("\n--- Summary ---")
    print(json.dumps(switcher.get_summary(), indent=2))
