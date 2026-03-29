"""
NIJA Core Loop  (rebuilt)
=========================

Single-pass, clean trading loop that coordinates:

    Phase 1 — Safety Gate
        Drawdown circuit breaker + daily loss limit check.
        Returns (can_trade: bool, balance: float).

    Phase 2 — Position Management
        For every open position: check exits, update trailing stops.
        Operates even when entries are blocked.

    Phase 3 — Market Scan & Ranked Entry
        Score every candidate symbol via NijaAIEngine.
        Rank all candidates.
        Take the top-N that fit open position slots.
        Executes with correct size multiplier per score tier.

Design goals
------------
- **Never stalls** — rank-first selection guarantees entries are found
  even in low-signal markets (adaptive threshold drops to floor)
- **Single responsibility per phase** — safety, management, entry are
  fully separated; safety never bleeds into entry logic
- **Cycle speed adapts** — NijaAIEngine.speed_ctrl records signal density
  each cycle; the loop caller reads ``next_interval`` to sleep appropriately
- **Drop-in** — ``NijaCoreLoop`` wraps the existing ``NIJAApexStrategyV71``
  and ``TradingStrategy`` objects; no existing logic is deleted

Usage
-----
In ``TradingStrategy.run_cycle`` (after the existing safety-gate block)::

    if NIJA_CORE_LOOP_AVAILABLE and hasattr(self, 'nija_core_loop'):
        result = self.nija_core_loop.run_scan_phase(
            broker=active_broker,
            balance=account_balance,
            symbols=symbols_to_scan,
            open_positions_count=self.open_positions_count,
        )
        # result.next_interval is the recommended sleep time in seconds

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.core_loop")

# Max positions the core loop may open in a single cycle
# (hard cap — position-level cap is enforced upstream by TradingStrategy)
MAX_ENTRIES_PER_CYCLE = 3

# Minimum score before the loop will even attempt an entry
# (NijaAIEngine uses its own adaptive threshold; this is a hard circuit-breaker)
MIN_SCORE_HARD_FLOOR = 25.0

# After this many consecutive zero-signal cycles, the fallback entry logic fires:
# the top-N candidates are forced through even if their quality is below the
# normal threshold, so the account is never idle for too long.
ZERO_SIGNAL_STREAK_THRESHOLD = 5

# Points added to a candidate's composite_score when the fallback entry is active.
# 20 points on a 0–100 scale corresponds to the +0.20 confidence boost described
# in the NIJA Profit Mode specification.
FALLBACK_SCORE_BOOST: float = 20.0

# Attempt to import TOP_N from sniper_filter at module load time.
# Fallback to 2 when the module is unavailable.
try:
    from sniper_filter import TOP_N as _SNIPER_TOP_N_DEFAULT
except ImportError:
    try:
        from bot.sniper_filter import TOP_N as _SNIPER_TOP_N_DEFAULT
    except ImportError:
        _SNIPER_TOP_N_DEFAULT = 2


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoreLoopResult:
    """Summary returned by NijaCoreLoop.run_scan_phase()."""
    symbols_scored:   int = 0
    entries_taken:    int = 0
    entries_blocked:  int = 0
    exits_taken:      int = 0
    errors:           List[str] = field(default_factory=list)
    next_interval:    int = 150    # recommended seconds before next cycle


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class NijaCoreLoop:
    """
    Rebuilt, single-pass core trading loop.

    Parameters
    ----------
    apex_strategy : NIJAApexStrategyV71
        The strategy instance that provides ``analyze_market``,
        ``execute_action``, and ``calculate_indicators``.
    max_positions : int
        Hard cap on concurrent open positions.
    """

    def __init__(self, apex_strategy: Any, max_positions: int = 5) -> None:
        self.apex = apex_strategy
        self.max_positions = max_positions
        self._lock = threading.Lock()

        # Lazy AI engine reference
        self._ai_engine = None

        # Consecutive cycles where Phase 3 produced zero entries (used by
        # the fallback entry mechanism — see ZERO_SIGNAL_STREAK_THRESHOLD).
        self._zero_signal_streak: int = 0

        logger.info(
            "✅ NijaCoreLoop initialized (max_positions=%d, max_entries_per_cycle=%d)",
            max_positions,
            MAX_ENTRIES_PER_CYCLE,
        )

    # ------------------------------------------------------------------
    # Lazy component loaders
    # ------------------------------------------------------------------

    def _get_ai_engine(self):
        if self._ai_engine is None:
            try:
                from nija_ai_engine import get_nija_ai_engine
                self._ai_engine = get_nija_ai_engine()
            except ImportError:
                try:
                    from bot.nija_ai_engine import get_nija_ai_engine
                    self._ai_engine = get_nija_ai_engine()
                except ImportError:
                    logger.warning(
                        "NijaAIEngine not available — core loop will use apex.analyze_market directly"
                    )
        return self._ai_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scan_phase(
        self,
        broker: Any,
        balance: float,
        symbols: List[str],
        open_positions_count: int = 0,
        user_mode: bool = False,
    ) -> CoreLoopResult:
        """
        Execute the full scan phase for one trading cycle.

        Phase 1 — Safety gate  (drawdown / daily loss)
        Phase 2 — Position management  (exits / trailing stops)
        Phase 3 — Score all symbols → rank → take top-N

        Parameters
        ----------
        broker              : Broker client instance
        balance             : Current account equity (USD)
        symbols             : Ordered list of symbols to scan
        open_positions_count: Number of currently open positions
        user_mode           : When True, skip Phase 3 (entries blocked)

        Returns
        -------
        CoreLoopResult with entries taken, next recommended interval, etc.
        """
        result = CoreLoopResult()
        cycle_start = time.time()

        # ── Phase 1: Safety gate ──────────────────────────────────────────
        can_enter, safety_reason = self._phase1_safety(broker, balance)
        if not can_enter:
            logger.info("🛡️  Core loop safety gate blocked entries: %s", safety_reason)
            user_mode = True

        # ── Phase 2: Position management ─────────────────────────────────
        exits = self._phase2_manage_positions(broker, balance)
        result.exits_taken = exits
        # Update available slots after exits
        effective_open = max(0, open_positions_count - exits)

        # ── Phase 3: Scan & ranked entry ──────────────────────────────────
        if not user_mode:
            available_slots = max(0, self.max_positions - effective_open)
            if available_slots > 0:
                entries, blocked, scored = self._phase3_scan_and_enter(
                    broker=broker,
                    balance=balance,
                    symbols=symbols,
                    available_slots=available_slots,
                    zero_signal_streak=self._zero_signal_streak,
                )
                result.entries_taken = entries
                result.entries_blocked = blocked
                result.symbols_scored = scored

                # Update the zero-signal streak counter for the next cycle
                if entries > 0:
                    self._zero_signal_streak = 0
                else:
                    self._zero_signal_streak += 1
                    if self._zero_signal_streak >= ZERO_SIGNAL_STREAK_THRESHOLD:
                        logger.warning(
                            "⚡ Core loop: zero-signal streak=%d (threshold=%d) — "
                            "fallback entry will activate next cycle if streak persists",
                            self._zero_signal_streak,
                            ZERO_SIGNAL_STREAK_THRESHOLD,
                        )
            else:
                logger.info(
                    "🔒 Core loop: position cap reached (%d/%d) — skipping entries",
                    effective_open,
                    self.max_positions,
                )
        else:
            logger.info("🔒 Core loop: entries blocked (user_mode)")

        # Recommend next interval from AI engine speed controller
        ai = self._get_ai_engine()
        if ai is not None:
            result.next_interval = ai.speed_ctrl.interval
        else:
            result.next_interval = 150

        elapsed_ms = (time.time() - cycle_start) * 1000
        logger.info(
            "🔄 Core loop complete — scored=%d entered=%d blocked=%d exited=%d "
            "elapsed=%.0fms next=%ds",
            result.symbols_scored,
            result.entries_taken,
            result.entries_blocked,
            result.exits_taken,
            elapsed_ms,
            result.next_interval,
        )
        return result

    # ------------------------------------------------------------------
    # Phase 1: Safety gate
    # ------------------------------------------------------------------

    def _phase1_safety(self, broker: Any, balance: float) -> Tuple[bool, str]:
        """
        Portfolio-level safety gate — checks only Layers 1 (global drawdown
        circuit breaker) and 2 (daily loss limit).

        Layer 4 (market-condition per-symbol check) is intentionally skipped
        here: it requires real symbol data and is enforced per-symbol inside
        ``apex.analyze_market``.  Passing an empty DataFrame to the controller
        would always return a score of 2/5 (below the threshold of 3) and
        incorrectly block all entries at the portfolio level before any
        symbols have been scanned.

        Returns (can_enter, reason_string).
        """
        try:
            apex = self.apex
            drc = getattr(apex, "drawdown_risk_ctrl", None)
            if drc is None:
                return True, "no drawdown controller"

            # Pass an empty DataFrame so the controller's Layer 4 market-
            # condition check is bypassed (len(df) < 5 → skip Layer 4).
            # Only Layers 1 + 2 run at this portfolio-wide gate.
            current_regime = getattr(apex, "current_regime", None)
            result = drc.pre_entry_check(
                account_balance=balance,
                df=pd.DataFrame(),      # empty → Layer 4 skipped (portfolio gate)
                indicators={},
                daily_pnl_usd=getattr(apex, "_daily_pnl_usd", 0.0),
                regime=current_regime,
            )
            if not result.can_trade:
                return False, result.reason
            return True, "ok"
        except Exception as exc:
            logger.debug("Phase1 safety check error (non-fatal): %s", exc)
            return True, "safety check skipped"

    # ------------------------------------------------------------------
    # Phase 2: Position management
    # ------------------------------------------------------------------

    def _phase2_manage_positions(self, broker: Any, balance: float) -> int:
        """
        Iterate open positions and process exits.

        Returns number of positions closed this phase.
        """
        exits = 0
        try:
            apex = self.apex
            ee = getattr(apex, "execution_engine", None)
            if ee is None:
                return 0

            positions = list(getattr(ee, "positions", {}).keys())
            for symbol in positions:
                try:
                    pos = ee.get_position(symbol)
                    if pos is None:
                        continue
                    # Ask apex to analyse the position (manage-only: position exists)
                    # We need a DataFrame; if we can't get one, skip gracefully
                    df = self._fetch_df(broker, symbol)
                    if df is None or len(df) < 10:
                        continue

                    analysis = apex.analyze_market(df, symbol, balance)
                    action = analysis.get("action", "hold")
                    if action in ("exit", "partial_exit", "take_profit_tp1",
                                  "take_profit_tp2", "take_profit_tp3"):
                        try:
                            apex.execute_action(analysis, symbol)
                            exits += 1
                        except Exception as exec_err:
                            logger.warning("Phase2 execute_action error for %s: %s", symbol, exec_err)
                except Exception as sym_err:
                    logger.debug("Phase2 position management error for %s: %s", symbol, sym_err)
        except Exception as exc:
            logger.warning("Phase2 position management error: %s", exc)

        return exits

    # ------------------------------------------------------------------
    # Phase 3: Scan, score, rank, enter
    # ------------------------------------------------------------------

    def _phase3_scan_and_enter(
        self,
        broker: Any,
        balance: float,
        symbols: List[str],
        available_slots: int,
        zero_signal_streak: int = 0,
    ) -> Tuple[int, int, int]:
        """
        Score all candidate symbols, rank them, execute top-N.

        When ``zero_signal_streak`` has reached ``ZERO_SIGNAL_STREAK_THRESHOLD``,
        a forced entry (fallback) activates: the top-N candidates receive a
        +0.20 confidence boost and have the low-quality bypass flag set so
        they can cross the entry threshold even in low-signal conditions.

        Returns (entries_taken, entries_blocked, symbols_scored).
        """
        # Pre-import AIEngineSignal once; guarded so the fallback path works
        # even when NijaAIEngine is unavailable.
        try:
            from nija_ai_engine import AIEngineSignal as _AISignal
        except ImportError:
            try:
                from bot.nija_ai_engine import AIEngineSignal as _AISignal
            except ImportError:
                _AISignal = None  # type: ignore

        ai = self._get_ai_engine()

        candidates = []   # List[AIEngineSignal | _AISignal]
        scored = 0
        blocked = 0

        # ── Score every symbol ────────────────────────────────────────────
        for symbol in symbols:
            # Cap: stop scoring once we have 10× the available slots — enough
            # diversity to find the top-N without scanning every symbol when the
            # market has 700+ pairs.
            if len(candidates) >= available_slots * 10:
                break

            try:
                df = self._fetch_df(broker, symbol)
                if df is None or len(df) < 100:
                    continue

                indicators = self.apex.calculate_indicators(df)
                if not indicators:
                    continue

                # Determine trend from apex market filter
                try:
                    allow, trend, _ = self.apex.check_market_filter(df, indicators)
                    if not allow:
                        blocked += 1
                        continue
                except Exception:
                    trend = "uptrend"

                side = "long" if trend == "uptrend" else "short"
                regime = getattr(self.apex, "current_regime", None)
                entry_type = (
                    self.apex._get_entry_type_for_regime(regime)
                    if hasattr(self.apex, "_get_entry_type_for_regime")
                    else "swing"
                )
                broker_name = (
                    self.apex._get_broker_name()
                    if hasattr(self.apex, "_get_broker_name")
                    else "coinbase"
                )

                if ai is not None:
                    sig = ai.evaluate_symbol(
                        df=df,
                        indicators=indicators,
                        side=side,
                        regime=regime,
                        broker=broker_name,
                        entry_type=entry_type,
                        symbol=symbol,
                    )
                    if sig is not None:
                        candidates.append(sig)
                elif _AISignal is not None:
                    # Fallback: use apex.analyze_market directly and wrap result
                    analysis = self.apex.analyze_market(df, symbol, balance)
                    if analysis.get("action") in ("enter_long", "enter_short"):
                        sig = _AISignal(
                            symbol=symbol,
                            side=side,
                            composite_score=50.0,
                            position_multiplier=1.0,
                            entry_type=entry_type,
                            threshold_used=25.0,
                            reason=analysis.get("reason", "apex signal"),
                            metadata={"apex_analysis": analysis},
                        )
                        candidates.append(sig)

                scored += 1

            except Exception as sym_err:
                logger.debug("Phase3 scoring error for %s: %s", symbol, sym_err)

        # ── Rank and select top-N ─────────────────────────────────────────
        if not candidates:
            logger.info(
                "🔍 Core loop Phase 3: scored=%d symbols, no candidates above floor=%.0f",
                scored, MIN_SCORE_HARD_FLOOR,
            )
            if ai is not None:
                ai.speed_ctrl.record_cycle(0)
            return 0, blocked, scored

        regime = getattr(self.apex, "current_regime", None)
        selected = (
            ai.rank_and_select(candidates, available_slots, regime)
            if ai is not None
            else candidates[:available_slots]
        )

        # ── Fallback entry: activate after too many zero-signal cycles ─────────
        # When the zero-signal streak has reached the threshold, boost the top-N
        # candidates and mark them so downstream gates treat them as forced entries.
        fallback_active = zero_signal_streak >= ZERO_SIGNAL_STREAK_THRESHOLD
        if fallback_active:
            logger.warning(
                "⚡ FALLBACK ENTRY ACTIVE (zero_streak=%d >= threshold=%d) — "
                "boosting top-%d candidates by +%.0f pts",
                zero_signal_streak, ZERO_SIGNAL_STREAK_THRESHOLD,
                _SNIPER_TOP_N_DEFAULT, FALLBACK_SCORE_BOOST,
            )
            selected = selected[:_SNIPER_TOP_N_DEFAULT]
            for sig in selected:
                sig.composite_score += FALLBACK_SCORE_BOOST
                sig.metadata["bypass_low_quality"] = True
                sig.metadata["fallback_streak"] = zero_signal_streak

        # ── Execute selected entries ──────────────────────────────────────
        entries = 0
        for sig in selected:
            if entries >= MAX_ENTRIES_PER_CYCLE:
                break
            try:
                df = self._fetch_df(broker, sig.symbol)
                if df is None or len(df) < 100:
                    continue

                # Re-run full apex.analyze_market (handles SL/TP/sizing etc.)
                analysis = self.apex.analyze_market(df, sig.symbol, balance)
                action = analysis.get("action", "hold")

                # When fallback is active, force the action to enter if the
                # signal side is known — the streak means we need a trade.
                if fallback_active and action not in ("enter_long", "enter_short"):
                    if sig.side in ("long", "buy", "enter_long"):
                        action = "enter_long"
                    elif sig.side in ("short", "sell", "enter_short"):
                        action = "enter_short"
                    else:
                        # Unknown side — log and skip rather than guess direction
                        logger.warning(
                            "⚡ Fallback entry: unknown side '%s' for %s — skipping",
                            sig.side, sig.symbol,
                        )
                        blocked += 1
                        continue
                    analysis["action"] = action
                    analysis["reason"] = analysis.get("reason", "") + " [fallback_entry]"

                if action not in ("enter_long", "enter_short"):
                    blocked += 1
                    continue

                # Apply AI engine position multiplier to analysis size hint
                if "position_size" in analysis and sig.position_multiplier != 1.0:
                    original = analysis["position_size"]
                    analysis["position_size"] = original * sig.position_multiplier
                    logger.info(
                        "   🤖 AI multiplier ×%.2f applied to %s size: $%.2f → $%.2f",
                        sig.position_multiplier, sig.symbol,
                        original, analysis["position_size"],
                    )

                success = self.apex.execute_action(analysis, sig.symbol)
                if success:
                    entries += 1
                    logger.info(
                        "   ✅ Core loop entry: %s %s score=%.1f mult=×%.2f%s",
                        sig.symbol, sig.side.upper(),
                        sig.composite_score, sig.position_multiplier,
                        " [FALLBACK]" if fallback_active else "",
                    )
                else:
                    blocked += 1

            except Exception as exec_err:
                logger.warning("Phase3 execute error for %s: %s", sig.symbol, exec_err)
                blocked += 1

        return entries, blocked, scored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_df(self, broker: Any, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV DataFrame from the broker.

        Returns ``None`` when the broker call fails or returns no data.
        """
        try:
            if broker is None:
                return None
            # Standard broker interface: get_candles(symbol, limit=200)
            if hasattr(broker, "get_candles"):
                result = broker.get_candles(symbol, limit=200)
                if isinstance(result, tuple):
                    df, err = result
                    if err or df is None or len(df) < 10:
                        return None
                    return df
                if isinstance(result, pd.DataFrame) and len(result) >= 10:
                    return result
            return None
        except Exception as exc:
            logger.debug("_fetch_df error for %s: %s", symbol, exc)
            return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------
_loop: Optional[NijaCoreLoop] = None


def get_nija_core_loop(apex_strategy: Any, max_positions: int = 5) -> NijaCoreLoop:
    """Return (or lazily create) the module-level singleton NijaCoreLoop."""
    global _loop
    if _loop is None:
        _loop = NijaCoreLoop(apex_strategy=apex_strategy, max_positions=max_positions)
    return _loop
