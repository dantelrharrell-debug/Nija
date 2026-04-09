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
import os
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
# Lowered 25.0 → 20.0 → 14.0 → 11.0 → 8.0 → 5.0 (micro-account mode, Apr 2026).
# Override at runtime with NIJA_CORE_MIN_SCORE env var.
MIN_SCORE_HARD_FLOOR = float(os.environ.get("NIJA_CORE_MIN_SCORE", "5.0"))

# ── DEAD ZONE detection ──────────────────────────────────────────────────────
# When zero_signal_streak reaches DEAD_ZONE_STREAK_THRESHOLD the bot is
# officially in a "dead zone" — normal AI scoring is producing nothing usable.
# In dead-zone mode TWO things happen simultaneously:
#   1. Momentum-Only Entry Mode activates (relaxed RSI 52/48 + vol check).
#   2. Volume fallback is enabled regardless of profit-mode level.
# This guarantees at least one candidate per cycle during range-bound markets.
DEAD_ZONE_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_DEAD_ZONE_STREAK", "2"))

# After this many consecutive zero-signal cycles, progressive score relaxation
# kicks in: each 3-cycle step (was 5) reduces the effective floor.
# Lowered 8 → 5 → 2 so relaxation triggers within 2 missed cycles.
FORCED_ENTRY_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_FORCED_ENTRY_STREAK", "2"))

# Number of relaxation steps (each step = 3 cycles past threshold).
MAX_RELAXATION_STEPS: int = 3

# Fractional threshold reduction per step:
#   step 1 (streak  2–4): factor 0.15 → floor × 0.85
#   step 2 (streak  5–7): factor 0.25 → floor × 0.75
#   step 3 (streak   ≥8): factor 0.40 → floor × 0.60  (hard cap)
_RELAXATION_SCHEDULE: Tuple[float, ...] = (0.0, 0.15, 0.25, 0.40)

# After this many consecutive zero-signal cycles, the hard bypass activates:
# all quality floors are ignored and the top-ranked available candidate is
# accepted unconditionally.  Lowered 40 → 10 → 8 → 5 → 3.
HARD_BYPASS_STREAK_THRESHOLD: int = int(os.environ.get("NIJA_HARD_BYPASS_STREAK", "3"))

# One-shot manual forced-entry flag.
# Set to True externally to force the top-scored candidate in the very next
# scan cycle, bypassing all quality filters.  The flag is automatically reset
# to False after a single cycle so exactly one trade is forced.
# Use module-level access for both reading and writing:
#   import bot.nija_core_loop as _cl
#   _cl.FORCE_NEXT_CYCLE = True   # force the next scan cycle
#   print(_cl.FORCE_NEXT_CYCLE)   # check current state
# Thread-safety note: the read-and-reset operation inside _phase3_scan_and_enter
# is protected by _FORCE_LOCK to prevent duplicate forced entries under
# concurrent callers.
FORCE_NEXT_CYCLE: bool = False
_FORCE_LOCK = threading.Lock()


def _get_relaxation_factor(streak: int) -> float:
    """Return threshold-reduction fraction for the given zero-signal streak.

    Returns 0.0 when below FORCED_ENTRY_STREAK_THRESHOLD.
    Caps at _RELAXATION_SCHEDULE[MAX_RELAXATION_STEPS] = 0.60.
    """
    if streak < FORCED_ENTRY_STREAK_THRESHOLD:
        return 0.0
    return _RELAXATION_SCHEDULE[_get_relaxation_step(streak)]


def _get_relaxation_step(streak: int) -> int:
    """Return the (1-based) relaxation step index for the given streak.

    step 1 → streak 2–4, step 2 → streak 5–7, step 3 → streak ≥ 8 (cap).
    Returns 0 when below FORCED_ENTRY_STREAK_THRESHOLD.
    """
    if streak < FORCED_ENTRY_STREAK_THRESHOLD:
        return 0
    cycles_past = streak - FORCED_ENTRY_STREAK_THRESHOLD
    return min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)


def _get_relaxation_factor_with_threshold(streak: int, threshold: int) -> float:
    """Variant of _get_relaxation_factor that accepts a custom streak threshold."""
    if streak < threshold:
        return 0.0
    cycles_past = streak - threshold
    step = min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)
    return _RELAXATION_SCHEDULE[step]


def _get_relaxation_step_with_threshold(streak: int, threshold: int) -> int:
    """Variant of _get_relaxation_step that accepts a custom streak threshold."""
    if streak < threshold:
        return 0
    cycles_past = streak - threshold
    return min(MAX_RELAXATION_STEPS, cycles_past // 3 + 1)

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
# Score Distribution Debugger — optional dependency
# ---------------------------------------------------------------------------
_SDD_AVAILABLE = False
_get_sdd = None  # type: ignore
try:
    from score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
    _SDD_AVAILABLE = True
except ImportError:
    try:
        from bot.score_distribution_debugger import get_score_debugger as _get_sdd  # type: ignore
        _SDD_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Profit Mode Controller — optional dependency
# ---------------------------------------------------------------------------
_PMC_AVAILABLE = False
_get_pmc = None  # type: ignore
try:
    from profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
    _PMC_AVAILABLE = True
except ImportError:
    try:
        from bot.profit_mode_controller import get_profit_mode_controller as _get_pmc  # type: ignore
        _PMC_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Momentum Entry Filter — relaxed dead-zone checkers
# ---------------------------------------------------------------------------
_MOMENTUM_FILTER_AVAILABLE = False
_check_mom_long_relaxed = None   # type: ignore
_check_mom_short_relaxed = None  # type: ignore
try:
    from momentum_entry_filter import (  # type: ignore
        check_momentum_long_relaxed as _check_mom_long_relaxed,
        check_momentum_short_relaxed as _check_mom_short_relaxed,
    )
    _MOMENTUM_FILTER_AVAILABLE = True
except ImportError:
    try:
        from bot.momentum_entry_filter import (  # type: ignore
            check_momentum_long_relaxed as _check_mom_long_relaxed,
            check_momentum_short_relaxed as _check_mom_short_relaxed,
        )
        _MOMENTUM_FILTER_AVAILABLE = True
    except ImportError:
        pass


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
        # the progressive relaxation mechanism — see FORCED_ENTRY_STREAK_THRESHOLD).
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
        broker              : Broker client instance (falls back to
                              ``apex.broker_client`` when None)
        balance             : Current account equity (USD)
        symbols             : Ordered list of symbols to scan
        open_positions_count: Number of currently open positions
        user_mode           : When True, skip Phase 3 (entries blocked)

        Returns
        -------
        CoreLoopResult with entries taken, next recommended interval, etc.
        """
        # ── Broker resolution: fall back to apex.broker_client when the
        # caller did not pass an explicit broker (or passed None).  This
        # covers the common case where run_scan_phase is called from
        # run_trading_loop → strategy.run_cycle without an explicit broker arg.
        if broker is None:
            broker = getattr(self.apex, "broker_client", None)

        # Guard: if still no broker or broker is disconnected, bail early so
        # individual per-symbol fetches don't silently return None for every
        # symbol and produce a zero-signal cycle.
        if broker is None or not getattr(broker, "connected", True):
            logger.warning(
                "🔴 Core loop: no broker connected — skipping scan phase "
                "(broker=%r connected=%r)",
                broker,
                getattr(broker, "connected", None) if broker is not None else None,
            )
            return CoreLoopResult()

        result = CoreLoopResult()
        cycle_start = time.time()

        logger.info(
            "🟢 Trading loop alive — scanning %d symbols (balance=$%.2f open=%d)",
            len(symbols), balance, open_positions_count,
        )

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
                logger.info(
                    "🔍 Scanning markets — %d symbols | slots=%d open=%d",
                    len(symbols), available_slots, effective_open,
                )
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
                    _relaxation = _get_relaxation_factor(self._zero_signal_streak)
                    if _relaxation > 0.0:
                        _step = _get_relaxation_step(self._zero_signal_streak)
                        logger.warning(
                            "⚡ Core loop: zero-signal streak=%d — "
                            "progressive relaxation step=%d/%d (factor=%.1f, floor×%.1f)",
                            self._zero_signal_streak,
                            _step, MAX_RELAXATION_STEPS, _relaxation, 1.0 - _relaxation,
                        )
                    elif self._zero_signal_streak == FORCED_ENTRY_STREAK_THRESHOLD - 1:
                        logger.info(
                            "⚡ Core loop: zero-signal streak=%d — "
                            "progressive relaxation activates next cycle (threshold=%d)",
                            self._zero_signal_streak,
                            FORCED_ENTRY_STREAK_THRESHOLD,
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

        When ``zero_signal_streak`` has reached ``FORCED_ENTRY_STREAK_THRESHOLD``,
        progressive score relaxation activates: each 5-cycle step reduces the
        effective MIN_SCORE_HARD_FLOOR by 10% (step 1), 15% (step 2), or 20%
        (step 3, capped).  Candidates below the relaxed floor are filtered out;
        remaining top-N are force-entered to prevent indefinite idling.

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

        # ── Read profit mode parameters (if available) ────────────────────
        # These override the module-level constants so runtime level changes
        # take effect immediately without restarting.
        _pmc_level = 0
        _effective_hard_floor = MIN_SCORE_HARD_FLOOR
        _effective_streak_threshold = FORCED_ENTRY_STREAK_THRESHOLD
        _effective_bypass_threshold = HARD_BYPASS_STREAK_THRESHOLD
        _volume_fallback_enabled = False
        if _PMC_AVAILABLE and _get_pmc is not None:
            try:
                _pmc_params = _get_pmc().params
                _pmc_level = _pmc_params.level
                _effective_hard_floor = _pmc_params.min_score_hard_floor
                _effective_streak_threshold = _pmc_params.forced_entry_streak_threshold
                _effective_bypass_threshold = _pmc_params.hard_bypass_streak_threshold
                _volume_fallback_enabled = _pmc_params.enable_volume_fallback
            except Exception as _exc:
                logger.debug("Phase3: profit mode params read failed — using module defaults: %s", _exc)

        # Dead-zone flag: volume fallback and Momentum-Only Entry Mode are
        # always active once zero_signal_streak reaches DEAD_ZONE_STREAK_THRESHOLD,
        # regardless of profit-mode level.
        _dead_zone = zero_signal_streak >= DEAD_ZONE_STREAK_THRESHOLD
        if _dead_zone:
            _volume_fallback_enabled = True
            logger.warning(
                "🌑 DEAD ZONE detected (streak=%d ≥ %d) — "
                "enabling momentum-only entry mode + volume fallback",
                zero_signal_streak, DEAD_ZONE_STREAK_THRESHOLD,
            )

        ai = self._get_ai_engine()

        candidates = []        # List[AIEngineSignal | _AISignal]  — AI-scored
        momentum_candidates = []  # collected from relaxed momentum scan
        scored = 0
        blocked = 0

        # Always-on top-volume tracker (feeds volume fallback for any streak)
        _best_volume_symbol: Optional[str] = None
        _best_volume_side: str = "long"
        _best_volume_entry_type: str = "swing"
        _best_volume: float = -1.0

        # Initialise the per-cycle score distribution debugger snapshot.
        _sdd = _get_sdd() if (_SDD_AVAILABLE and _get_sdd is not None) else None
        if _sdd is not None:
            _sdd.start_cycle()

        # ── Score every symbol ────────────────────────────────────────────
        for symbol in symbols:
            # Cap: stop scoring once we have 10× the available slots — enough
            # diversity to find the top-N without scanning every symbol when the
            # market has 700+ pairs.
            if len(candidates) >= available_slots * 10:
                if _sdd is not None:
                    _sdd.record_skip(symbol, "cap_reached")
                break

            try:
                df = self._fetch_df(broker, symbol)
                if df is None or len(df) < 100:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "data_insufficient")
                    continue

                # Always track top-volume symbol (feeds volume fallback)
                if "volume" in df.columns:
                    try:
                        avg_vol = float(df["volume"].tail(20).mean())
                        if avg_vol > _best_volume:
                            _best_volume = avg_vol
                            _best_volume_symbol = symbol
                    except Exception:
                        pass

                indicators = self.apex.calculate_indicators(df)
                if not indicators:
                    if _sdd is not None:
                        _sdd.record_skip(symbol, "indicators_failed")
                    continue

                # Determine trend from apex market filter
                try:
                    allow, trend, _ = self.apex.check_market_filter(df, indicators)
                    if not allow:
                        blocked += 1
                        if _sdd is not None:
                            _sdd.record_skip(symbol, "market_filter")
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

                # Update top-volume side/entry_type to match the best symbol's context
                if symbol == _best_volume_symbol:
                    _best_volume_side = side
                    _best_volume_entry_type = entry_type

                # ── Standard AI scoring ───────────────────────────────────
                if ai is not None:
                    logger.debug("🔎 Evaluating signal — %s (%s)", symbol, side)
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

                # ── Momentum-Only Entry Mode (dead zone) ──────────────────
                # When in a dead zone run the lightweight relaxed momentum
                # checker on every symbol.  Passing symbols are collected as
                # B/C grade candidates (score pinned to TIER_FLOOR) regardless
                # of whether they passed the full AI scoring above.
                if _dead_zone and _MOMENTUM_FILTER_AVAILABLE and _AISignal is not None:
                    try:
                        if side == "long" and _check_mom_long_relaxed is not None:
                            mom_ok, mom_score, mom_reason = _check_mom_long_relaxed(df, indicators)
                        elif side == "short" and _check_mom_short_relaxed is not None:
                            mom_ok, mom_score, mom_reason = _check_mom_short_relaxed(df, indicators)
                        else:
                            mom_ok = False
                        if mom_ok:
                            momentum_candidates.append(_AISignal(
                                symbol=symbol,
                                side=side,
                                composite_score=_effective_hard_floor,
                                position_multiplier=0.75,   # B/C grade — reduced size
                                entry_type="momentum",
                                threshold_used=_effective_hard_floor,
                                reason=f"[MOMENTUM_ONLY] {mom_reason}",
                                metadata={
                                    "dead_zone": True,
                                    "momentum_score": mom_score,
                                    "bypass_low_quality": True,
                                    "weak_signal_entry": True,
                                },
                            ))
                    except Exception as _me:
                        logger.debug("Momentum-Only check failed for %s: %s", symbol, _me)

                scored += 1

            except Exception as sym_err:
                logger.debug("Phase3 scoring error for %s: %s", symbol, sym_err)
                if _sdd is not None:
                    _sdd.record_skip(symbol, "exception")

        # ── Merge momentum candidates when AI candidates are scarce ──────
        # If we're in dead-zone mode and have fewer AI candidates than slots,
        # pad from the momentum list (highest-score first) up to available_slots.
        if _dead_zone and momentum_candidates and len(candidates) < available_slots:
            # Deduplicate — don't add a momentum candidate for a symbol already
            # represented in the AI-scored list.
            existing_symbols = {s.symbol for s in candidates}
            new_mom = [s for s in momentum_candidates if s.symbol not in existing_symbols]
            # Sort by score descending, take as many as needed to fill slots
            new_mom.sort(key=lambda s: s.composite_score, reverse=True)
            slots_needed = available_slots - len(candidates)
            candidates.extend(new_mom[:slots_needed])
            if new_mom:
                logger.warning(
                    "🔥 MOMENTUM-ONLY MODE — injecting %d/%d momentum candidates "
                    "(streak=%d, slots_needed=%d)",
                    min(len(new_mom), slots_needed), len(new_mom),
                    zero_signal_streak, slots_needed,
                )

        # ── Volume fallback: inject top-volume candidate when still empty ─
        # Active whenever _volume_fallback_enabled (always true in dead zone;
        # also true for profit-mode Level 3).
        if not candidates and _volume_fallback_enabled and _best_volume_symbol and _AISignal is not None:
            logger.warning(
                "💰 VOLUME FALLBACK — no candidates after momentum scan; "
                "injecting highest-volume symbol: %s (avg_vol=%.0f)",
                _best_volume_symbol, _best_volume,
            )
            fallback_sig = _AISignal(
                symbol=_best_volume_symbol,
                side=_best_volume_side,
                composite_score=_effective_hard_floor,
                position_multiplier=0.50,               # conservative micro-trade size
                entry_type=_best_volume_entry_type,
                threshold_used=_effective_hard_floor,
                reason="volume_fallback_guaranteed_activity",
                metadata={
                    "profit_mode_level": _pmc_level,
                    "volume_fallback": True,
                    "avg_volume": _best_volume,
                    "bypass_low_quality": True,
                    "dead_zone": _dead_zone,
                },
            )
            candidates.append(fallback_sig)

        # ── Rank and select top-N ─────────────────────────────────────────
        if not candidates:
            logger.info(
                "🔍 Core loop Phase 3: scored=%d symbols, no candidates above floor=%.0f",
                scored, _effective_hard_floor,
            )
            if _sdd is not None:
                _sdd.emit_histogram(
                    entries_taken=0,
                    candidates_found=0,
                    rank_threshold=None,
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

        # ── Progressive relaxation: activate after too many zero-signal cycles ──
        # Each 3-cycle step reduces the effective floor by 15% / 25% / 40%.
        _relaxation = _get_relaxation_factor_with_threshold(
            zero_signal_streak, _effective_streak_threshold
        )
        fallback_active = _relaxation > 0.0
        if fallback_active:
            _step = _get_relaxation_step_with_threshold(
                zero_signal_streak, _effective_streak_threshold
            )
            _relaxed_floor = _effective_hard_floor * (1.0 - _relaxation)
            logger.warning(
                "⚡ PROGRESSIVE RELAXATION step=%d/%d "
                "(streak=%d factor=%.0f%% floor=%.1f→%.1f) — top-%d eligible",
                _step, MAX_RELAXATION_STEPS,
                zero_signal_streak, _relaxation * 100,
                _effective_hard_floor, _relaxed_floor,
                _SNIPER_TOP_N_DEFAULT,
            )
            # Filter to candidates above the relaxed floor, then take top-N
            eligible = [s for s in selected if s.composite_score >= _relaxed_floor]
            selected = eligible[:_SNIPER_TOP_N_DEFAULT]
            for sig in selected:
                sig.metadata["bypass_low_quality"] = True
                sig.metadata["relaxation_factor"] = _relaxation
                sig.metadata["relaxation_step"] = _step
                sig.metadata["fallback_streak"] = zero_signal_streak

        # ── Hard bypass: consecutive zero-signal cycles → accept best available ──
        # Threshold uses profit mode value so Level 2/3 bypass sooner.
        if zero_signal_streak >= _effective_bypass_threshold:
            if not selected and candidates:
                # Quality floors filtered everything — pick the single best candidate
                top_candidate = max(candidates, key=lambda s: s.composite_score)
                selected = [top_candidate]
                logger.warning(
                    "🚨 HARD BYPASS activated (streak=%d ≥ %d) — quality floor "
                    "bypassed, forcing top candidate %s (score=%.1f)",
                    zero_signal_streak, _effective_bypass_threshold,
                    top_candidate.symbol, top_candidate.composite_score,
                )
            fallback_active = True  # ensure forced-entry path runs for selected signals
            for sig in selected:
                sig.metadata["bypass_quality_filter"] = True
                sig.metadata["hard_bypass_streak"] = zero_signal_streak

        # ── One-cycle forced entry (FORCE_NEXT_CYCLE flag) ───────────────
        # When FORCE_NEXT_CYCLE is True the top-scored candidate is selected
        # unconditionally, all quality filters are bypassed, and the flag is
        # immediately reset so exactly one cycle is forced.
        # _FORCE_LOCK ensures the read-and-reset is atomic under concurrent callers.
        global FORCE_NEXT_CYCLE
        with _FORCE_LOCK:
            _force_this_cycle = FORCE_NEXT_CYCLE
            if _force_this_cycle:
                FORCE_NEXT_CYCLE = False  # reset atomically — one-shot only
        if _force_this_cycle and candidates:
            top_candidate = max(candidates, key=lambda s: s.composite_score)
            top_candidate.metadata["bypass_quality_filter"] = True
            top_candidate.metadata["hard_bypass_streak"] = zero_signal_streak
            for c in candidates:
                logger.info(
                    "🔹 Candidate: %s | Score: %.1f",
                    getattr(c, "symbol", "UNKNOWN"),
                    c.composite_score,
                )
            logger.warning(
                "🚀 FORCE_NEXT_CYCLE active — forcing entry on top candidate "
                "%s (score=%.1f, streak=%d)",
                top_candidate.symbol,
                top_candidate.composite_score,
                zero_signal_streak,
            )
            selected = [top_candidate]
            fallback_active = True  # ensure the execution block forces the action

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
                        f" [RELAX×{sig.metadata.get('relaxation_step', 0)}]" if fallback_active else "",
                    )
                else:
                    blocked += 1

            except Exception as exec_err:
                logger.warning("Phase3 execute error for %s: %s", sig.symbol, exec_err)
                blocked += 1

        # ── Emit score histogram for this cycle ──────────────────────────
        if _sdd is not None:
            rank_threshold = selected[0].threshold_used if selected else None
            _sdd.emit_histogram(
                entries_taken=entries,
                candidates_found=len(candidates),
                rank_threshold=rank_threshold,
            )

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


# ---------------------------------------------------------------------------
# Standalone trading loop — for use as a daemon thread target
# ---------------------------------------------------------------------------
# _loop_guard / _loop_running guard against duplicate loop starts:
#   - _loop_guard  : Lock that serialises the check-and-set on _loop_running.
#   - _loop_running: Flag set to True the first time run_trading_loop acquires
#                    the lock; subsequent callers bail out immediately so only
#                    one continuous cycle ever runs.
_loop_guard = threading.Lock()
_loop_running = False


def run_trading_loop(strategy: Any, cycle_secs: int = 150) -> None:
    """
    Continuous self-healing trading loop.

    Designed to be launched as a daemon thread target directly from
    TradingStrategy initialisation so the core trading cycle is
    guaranteed to start even if the outer orchestrator (bot.py) hits
    an unexpected exception before starting its own threads.

    Parameters
    ----------
    strategy   : TradingStrategy instance
    cycle_secs : Seconds to sleep between cycles (default 150 = 2.5 min)

    Usage
    -----
    threading.Thread(
        target=nija_core_loop.run_trading_loop,
        args=(self,),
        daemon=True,
    ).start()
    """
    global _loop_running

    with _loop_guard:
        if _loop_running:
            logger.info("🟡 Core trading loop already active — skipping duplicate start")
            return
        _loop_running = True

    logger.info("🟢 Trading loop alive (INITIAL START)")

    cycle = 0
    while True:
        try:
            cycle += 1
            strategy.run_cycle()
            time.sleep(cycle_secs)
        except Exception as _err:
            logger.error(
                "❌ Trading loop cycle #%d error: %s — retrying in 15s",
                cycle,
                _err,
                exc_info=True,
            )
            time.sleep(15)
