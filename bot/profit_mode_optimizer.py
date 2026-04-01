"""
NIJA Profit Mode Optimizer
===========================

Profit-focused optimization layer that shifts the bot from *trade-frequency*
mode into *profit-quality* mode.  Three components work in concert:

1. **DynamicTPScaler**
   Returns a market-dependent take-profit multiplier (0.6×–2.5×) that widens
   targets in strong trends and volatile breakouts, and tightens them in choppy
   or mean-reverting regimes.  Inputs: market regime, ATR ratio, ADX / trend
   strength, and a short win/loss streak adjustment.

2. **WinRateAutoAdjuster**
   Maintains a rolling window of trade outcomes.  When the rolling win rate
   drifts below the target floor (default 55 %) the adjuster tightens TP
   (take profits faster, lock in smaller wins) and raises the minimum entry
   score requirement.  When win rate is comfortably above the target ceiling
   (default 65 %) it loosens TP to capture larger moves and relaxes the entry
   score floor.

3. **PairRankingOptimizer**
   Computes a composite *profit score* for each symbol using per-pair PnL
   analytics: ``win_rate × avg_return_usd × profit_factor / volatility_penalty``.
   Returns a ranked list of symbols with a recommended position-size multiplier
   (top tier: 1.35×, mid tier: 1.15×, base: 1.0×, low tier: 0.75×).  Feeds
   directly into the scan loop so the bot naturally concentrates capital in
   proven pairs.

Architecture
------------
::

    ProfitModeOptimizer (singleton via get_profit_mode_optimizer())
    │
    ├── tp_scaler:  DynamicTPScaler
    │     get_tp_multiplier(regime, atr_pct, adx, win_streak) → float
    │
    ├── win_adjuster: WinRateAutoAdjuster
    │     record_outcome(is_win) → None
    │     get_tp_adjustment() → float        # 0.70–1.30
    │     get_score_adjustment() → float     # additive delta on entry score
    │
    └── pair_ranker: PairRankingOptimizer
          get_pair_score(symbol) → float        # 0.0–1.0 composite
          get_pair_size_multiplier(symbol) → float
          get_ranked_symbols(symbols) → List[str]   # sorted best→worst
          get_report() → dict

Usage
-----
::

    from bot.profit_mode_optimizer import get_profit_mode_optimizer

    pmo = get_profit_mode_optimizer()

    # ── Dynamic TP scaling ──────────────────────────────────────────────────
    tp_mult = pmo.tp_scaler.get_tp_multiplier(
        regime="trending",
        atr_pct=0.022,          # ATR / price
        adx=32.0,
        win_streak=2,
    )
    # Scale TP list in analysis dict
    for i, tp in enumerate(analysis.get('take_profit', [])):
        if tp and entry_price:
            dist = abs(tp - entry_price)
            analysis['take_profit'][i] = entry_price + dist * tp_mult  # long

    # ── Win-rate feedback ───────────────────────────────────────────────────
    pmo.win_adjuster.record_outcome(is_win=True)
    tp_adj      = pmo.win_adjuster.get_tp_adjustment()      # 1.10 = wider TP
    score_delta = pmo.win_adjuster.get_score_adjustment()   # +2.0 = stricter

    # ── Pair ranking ────────────────────────────────────────────────────────
    size_mult = pmo.pair_ranker.get_pair_size_multiplier("BTC-USD")
    ranked    = pmo.pair_ranker.get_ranked_symbols(candidate_symbols)

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.profit_mode_optimizer")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dynamic TP Scaler
# ─────────────────────────────────────────────────────────────────────────────

# Regime → base TP multiplier.  Values tuned to match NIJA execution profiles
# (see execution_exit_config.py for SL/TP %-ranges per regime).
_REGIME_BASE_TP: Dict[str, float] = {
    "trending":       1.45,   # strong directional move → wider target
    "breakout":       1.55,   # momentum breakout → let it run
    "volatile":       1.20,   # high vol → still room to capture but risks snap-back
    "ranging":        0.85,   # choppy → take profits faster
    "mean_reverting": 0.80,   # reversion → small target, exit before reversion reverses
    "bear":           0.90,   # downtrend bias → conservative longs
    "bull":           1.30,   # sustained uptrend → slightly wider
    "unknown":        1.00,   # fallback neutral
}

# ATR-percentage breakpoints: [threshold, multiplier_delta]
# If ATR%  > 0.04 (4 %) market is very volatile → expand TP further.
# If ATR% < 0.01 (1 %) market is very quiet   → tighten TP.
_ATR_ADJUSTMENTS: Tuple[Tuple[float, float], ...] = (
    (0.050, +0.30),   # very high volatility
    (0.035, +0.15),
    (0.020, +0.05),
    (0.010, -0.05),
    (0.005, -0.15),   # micro volatility
)

# ADX trend-strength breakpoints: [threshold, multiplier_delta]
_ADX_ADJUSTMENTS: Tuple[Tuple[float, float], ...] = (
    (50.0, +0.25),    # extremely strong trend
    (40.0, +0.15),
    (30.0, +0.07),
    (20.0,  0.00),    # neutral
    (10.0, -0.10),    # no trend / noise
)

# Win/loss streak adjustments (clamped to ±3).
_STREAK_ADJUSTMENT: float = 0.05   # per trade in streak (± 0.05 per step)

_TP_MULT_MIN: float = 0.60
_TP_MULT_MAX: float = 2.50


class DynamicTPScaler:
    """
    Returns a floating-point multiplier that should be applied to the
    *distance* between entry price and the current take-profit level.

    A multiplier of 1.0 leaves TP unchanged; > 1.0 widens it; < 1.0 tightens.

    Args:
        regime:      Market regime string (e.g. "trending", "ranging").
        atr_pct:     ATR expressed as a fraction of current price (e.g. 0.022).
        adx:         ADX value (0–100), or 0.0 if unavailable.
        win_streak:  Positive = consecutive wins; negative = consecutive losses.
    """

    def get_tp_multiplier(
        self,
        regime: str = "unknown",
        atr_pct: float = 0.015,
        adx: float = 0.0,
        win_streak: int = 0,
    ) -> float:
        """Compute and return the TP distance multiplier."""
        mult = _REGIME_BASE_TP.get(regime.lower() if regime else "unknown",
                                   _REGIME_BASE_TP["unknown"])

        # ATR adjustment
        for threshold, delta in _ATR_ADJUSTMENTS:
            if atr_pct >= threshold:
                mult += delta
                break

        # ADX adjustment
        for threshold, delta in _ADX_ADJUSTMENTS:
            if adx >= threshold:
                mult += delta
                break

        # Win/loss streak adjustment (capped at ±3 steps)
        streak_capped = max(-3, min(3, win_streak))
        mult += streak_capped * _STREAK_ADJUSTMENT

        mult = max(_TP_MULT_MIN, min(_TP_MULT_MAX, mult))
        logger.debug(
            "[DynamicTPScaler] regime=%s atr_pct=%.4f adx=%.1f streak=%d → ×%.3f",
            regime, atr_pct, adx, win_streak, mult,
        )
        return round(mult, 4)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Win Rate Auto Adjuster
# ─────────────────────────────────────────────────────────────────────────────

# Rolling window length for win-rate calculation.
_WIN_RATE_WINDOW: int = 30

# Target win-rate band.  Outside this band the adjuster nudges parameters.
_WIN_RATE_TARGET_FLOOR: float = 0.55    # below this → tighten TP, raise score req
_WIN_RATE_TARGET_CEILING: float = 0.65  # above this → widen TP, relax score req

# Maximum adjustment magnitudes.
_MAX_TP_ADJ: float = 0.30     # TP factor can shift by at most ±30 %
_MAX_SCORE_ADJ: float = 5.0   # entry score can shift by at most ±5 pts


@dataclass
class _WinRateState:
    total_recorded: int = 0
    wins: int = 0


class WinRateAutoAdjuster:
    """
    Tracks a rolling win rate and returns continuous adjustment factors.

    * ``get_tp_adjustment()``   — multiply TP distance by this factor.
    * ``get_score_adjustment()`` — add this delta to minimum entry score.

    When win rate < floor: TP shrinks (< 1.0) and score delta is positive
    (tighter filtering → only better setups enter).

    When win rate > ceiling: TP expands (> 1.0) and score delta is negative
    (a bit more relaxed → capture more of the good setup pool).
    """

    def __init__(self, window: int = _WIN_RATE_WINDOW) -> None:
        self._window: Deque[bool] = deque(maxlen=window)
        self._state = _WinRateState()
        self._lock = threading.Lock()

    def record_outcome(self, is_win: bool) -> None:
        """Record the result of a closed trade (True = win, False = loss)."""
        with self._lock:
            self._window.append(is_win)
            self._state.total_recorded += 1
            if is_win:
                self._state.wins += 1

    def get_current_win_rate(self) -> float:
        """Return win rate over the rolling window (0.0–1.0)."""
        with self._lock:
            if not self._window:
                return 0.60   # neutral default before any data
            return sum(1 for w in self._window if w) / len(self._window)

    def get_tp_adjustment(self) -> float:
        """
        Return a TP distance multiplier driven by recent win rate.

        * wr  < floor   → 1.0 − proportional_tightening (down to 1 − _MAX_TP_ADJ)
        * wr  in band   → 1.0
        * wr  > ceiling → 1.0 + proportional_widening  (up to 1 + _MAX_TP_ADJ)
        """
        wr = self.get_current_win_rate()
        if wr < _WIN_RATE_TARGET_FLOOR:
            # How far below floor (0→1 where 1 = all losses)
            severity = (_WIN_RATE_TARGET_FLOOR - wr) / _WIN_RATE_TARGET_FLOOR
            adj = 1.0 - severity * _MAX_TP_ADJ
        elif wr > _WIN_RATE_TARGET_CEILING:
            # How far above ceiling (0→1 where 1 = all wins)
            strength = (wr - _WIN_RATE_TARGET_CEILING) / (1.0 - _WIN_RATE_TARGET_CEILING)
            adj = 1.0 + strength * _MAX_TP_ADJ
        else:
            adj = 1.0
        return round(max(1.0 - _MAX_TP_ADJ, min(1.0 + _MAX_TP_ADJ, adj)), 4)

    def get_score_adjustment(self) -> float:
        """
        Return an additive delta for the minimum entry score.

        Positive delta → raise the bar (tighter filtering).
        Negative delta → lower the bar slightly.
        """
        wr = self.get_current_win_rate()
        if wr < _WIN_RATE_TARGET_FLOOR:
            severity = (_WIN_RATE_TARGET_FLOOR - wr) / _WIN_RATE_TARGET_FLOOR
            delta = severity * _MAX_SCORE_ADJ          # raise score floor
        elif wr > _WIN_RATE_TARGET_CEILING:
            strength = (wr - _WIN_RATE_TARGET_CEILING) / (1.0 - _WIN_RATE_TARGET_CEILING)
            delta = -(strength * (_MAX_SCORE_ADJ / 2))  # slight relaxation
        else:
            delta = 0.0
        return round(max(-_MAX_SCORE_ADJ, min(_MAX_SCORE_ADJ, delta)), 4)

    def get_report(self) -> dict:
        """Return a snapshot of current win-rate state."""
        with self._lock:
            wr = self.get_current_win_rate()
            return {
                "rolling_win_rate":    round(wr, 4),
                "rolling_window_size": len(self._window),
                "total_recorded":      self._state.total_recorded,
                "tp_adjustment":       self.get_tp_adjustment(),
                "score_adjustment":    self.get_score_adjustment(),
                "target_floor":        _WIN_RATE_TARGET_FLOOR,
                "target_ceiling":      _WIN_RATE_TARGET_CEILING,
            }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pair Ranking Optimizer
# ─────────────────────────────────────────────────────────────────────────────

# Minimum trades before a pair earns a non-neutral ranking score.
_RANK_MIN_TRADES: int = 10

# Multiplier tiers assigned based on normalized composite score.
_RANK_TIER_TOP:  float = 1.35   # top 20 % of scored pairs
_RANK_TIER_MID:  float = 1.15   # 20–50 % band
_RANK_TIER_BASE: float = 1.00   # 50–80 % band (neutral)
_RANK_TIER_LOW:  float = 0.75   # bottom 20 % (reduce, but don't kill)

# Volatility penalty cap — very volatile pairs are penalized up to this factor.
_VOL_PENALTY_MAX: float = 2.0


@dataclass
class _PairRankState:
    """Lightweight per-symbol rank cache."""
    symbol: str
    score: float = 0.5    # neutral default
    multiplier: float = 1.0


class PairRankingOptimizer:
    """
    Scores every symbol on a composite profitability metric and exposes a
    ranked list as well as per-symbol position-size multipliers.

    The composite score formula is:

        raw = win_rate × avg_return_usd × profit_factor
        vol_penalty = 1 + min(abs(avg_loss_usd) / max(avg_return_usd, 0.01), VOL_PENALTY_MAX - 1)
        score = raw / vol_penalty   (clamped to 0–∞, then normalized per batch)

    The score is then min-max normalised across all ranked symbols so the
    multiplier assignment is relative (always a top / mid / base / low tier).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, _PairRankState] = {}
        # Lazy PnLAnalyticsLayer reference to avoid circular import.
        self._analytics = None

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_analytics(self):
        if self._analytics is None:
            try:
                from pnl_analytics_layer import get_pnl_analytics_layer
                self._analytics = get_pnl_analytics_layer()
            except ImportError:
                try:
                    from bot.pnl_analytics_layer import get_pnl_analytics_layer
                    self._analytics = get_pnl_analytics_layer()
                except ImportError:
                    pass
        return self._analytics

    def _compute_raw_score(self, symbol: str) -> Optional[float]:
        """Return raw composite score for *symbol*, or None if insufficient data.

        Expected ``PairStats`` attributes from ``PnLAnalyticsLayer.get_pair_stats()``:
          - ``total_trades``  (int)
          - ``win_rate``      (float, 0-1)
          - ``profit_factor`` (float, ≥ 0)
          - ``total_pnl_usd`` (float)
          - ``avg_profit_usd`` (float, optional — per-win average P&L)
          - ``avg_loss_usd``   (float, optional — per-loss average P&L, signed or abs)
        """
        analytics = self._get_analytics()
        if analytics is None:
            return None
        try:
            ps = analytics.get_pair_stats(symbol)
        except Exception:
            return None
        if ps is None or ps.total_trades < _RANK_MIN_TRADES:
            return None

        wr = max(0.0, ps.win_rate)
        # Prefer per-win avg profit; fall back to overall avg P&L per trade.
        avg_ret = getattr(ps, 'avg_profit_usd', None)
        if avg_ret is None:
            avg_ret = ps.total_pnl_usd / max(ps.total_trades, 1)
        avg_ret = float(avg_ret)
        pf = max(0.01, ps.profit_factor)

        # Volatility penalty: larger per-loss size relative to per-win size → penalize.
        # ``avg_loss_usd`` may be signed negative; we take absolute value.
        # If unavailable, derive a rough estimate from profit_factor:
        # pf = total_win / total_loss → avg_loss ≈ (avg_ret * wins) / (pf * losses).
        avg_loss_raw = getattr(ps, 'avg_loss_usd', None)
        if avg_loss_raw is None:
            # Rough estimate: if pf > 0, avg_loss = avg_ret / pf (same trade count assumption)
            avg_loss = abs(avg_ret) / max(pf, 0.01) if avg_ret > 0 else 0.0
        else:
            avg_loss = abs(float(avg_loss_raw))

        vol_penalty = 1.0 + min(avg_loss / max(abs(avg_ret), 0.01),
                                 _VOL_PENALTY_MAX - 1.0)

        raw = wr * max(avg_ret, 0.0) * pf / vol_penalty
        return raw

    def _refresh_cache(self, symbols: Optional[List[str]] = None) -> None:
        """Re-compute scores for *symbols* (or all cached) and assign multipliers."""
        analytics = self._get_analytics()
        if analytics is None:
            return

        # Determine which symbols to score
        if symbols is None:
            try:
                symbols = [ps.symbol for ps in analytics.get_all_pair_stats()]
            except Exception:
                return

        raw_scores: Dict[str, float] = {}
        for sym in symbols:
            score = self._compute_raw_score(sym)
            if score is not None:
                raw_scores[sym] = score

        if not raw_scores:
            return

        # Min-max normalise across the batch
        min_s = min(raw_scores.values())
        max_s = max(raw_scores.values())
        span = max_s - min_s if (max_s - min_s) > 1e-9 else 1.0

        ranked = sorted(raw_scores.items(), key=lambda kv: kv[1], reverse=True)
        n = len(ranked)
        for idx, (sym, raw) in enumerate(ranked):
            norm_score = (raw - min_s) / span          # 0.0–1.0
            percentile = 1.0 - (idx / max(n - 1, 1))  # 1.0 = best, 0.0 = worst

            if percentile >= 0.80:
                mult = _RANK_TIER_TOP
            elif percentile >= 0.50:
                mult = _RANK_TIER_MID
            elif percentile >= 0.20:
                mult = _RANK_TIER_BASE
            else:
                mult = _RANK_TIER_LOW

            self._cache[sym] = _PairRankState(
                symbol=sym, score=round(norm_score, 4), multiplier=mult
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_pair_score(self, symbol: str) -> float:
        """
        Return the normalized composite score (0.0–1.0) for *symbol*.

        Returns 0.5 (neutral) if insufficient data or not yet ranked.
        """
        with self._lock:
            state = self._cache.get(symbol)
            if state is None:
                # Attempt a lazy single-symbol refresh
                self._refresh_cache(symbols=[symbol])
                state = self._cache.get(symbol)
            return state.score if state is not None else 0.5

    def get_pair_size_multiplier(self, symbol: str) -> float:
        """
        Return the position-size multiplier for *symbol* (0.75–1.35).

        Defaults to 1.0 (neutral) when data is unavailable.
        """
        with self._lock:
            state = self._cache.get(symbol)
            if state is None:
                self._refresh_cache(symbols=[symbol])
                state = self._cache.get(symbol)
            return state.multiplier if state is not None else 1.0

    def get_ranked_symbols(self, symbols: List[str]) -> List[str]:
        """
        Return *symbols* sorted from highest to lowest composite profit score.

        Symbols with insufficient data retain their original relative position
        (they are treated as neutral and placed after ranked symbols).
        """
        with self._lock:
            self._refresh_cache(symbols=symbols)
            scored: List[Tuple[str, float]] = []
            unscored: List[str] = []
            for sym in symbols:
                state = self._cache.get(sym)
                if state is not None and state.score != 0.5:
                    scored.append((sym, state.score))
                else:
                    unscored.append(sym)
            scored.sort(key=lambda kv: kv[1], reverse=True)
            return [sym for sym, _ in scored] + unscored

    def get_report(self) -> dict:
        """Return a summary of current pair rankings."""
        with self._lock:
            ranked = sorted(
                self._cache.items(),
                key=lambda kv: kv[1].score,
                reverse=True,
            )
            return {
                "total_ranked_pairs": len(ranked),
                "top_pairs": [
                    {"symbol": sym, "score": st.score, "size_mult": st.multiplier}
                    for sym, st in ranked[:10]
                ],
                "bottom_pairs": [
                    {"symbol": sym, "score": st.score, "size_mult": st.multiplier}
                    for sym, st in ranked[-5:]
                ],
                "tier_top_count": sum(1 for _, st in ranked if st.multiplier == _RANK_TIER_TOP),
                "tier_low_count": sum(1 for _, st in ranked if st.multiplier == _RANK_TIER_LOW),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Composite facade
# ─────────────────────────────────────────────────────────────────────────────

class ProfitModeOptimizer:
    """
    Facade that bundles the three profit-quality optimization components.

    Attributes:
        tp_scaler:    :class:`DynamicTPScaler`
        win_adjuster: :class:`WinRateAutoAdjuster`
        pair_ranker:  :class:`PairRankingOptimizer`
    """

    def __init__(self, win_rate_window: int = _WIN_RATE_WINDOW) -> None:
        self.tp_scaler    = DynamicTPScaler()
        self.win_adjuster = WinRateAutoAdjuster(window=win_rate_window)
        self.pair_ranker  = PairRankingOptimizer()
        logger.info(
            "✅ ProfitModeOptimizer ready — "
            "DynamicTPScaler + WinRateAutoAdjuster(window=%d) + PairRankingOptimizer",
            win_rate_window,
        )

    def get_tp_multiplier(
        self,
        regime: str = "unknown",
        atr_pct: float = 0.015,
        adx: float = 0.0,
        win_streak: int = 0,
    ) -> float:
        """
        Combined TP multiplier: DynamicTPScaler × WinRateAutoAdjuster.

        The win-adjuster factor layers on top of the regime/ATR/ADX scaling
        so that a deteriorating win rate tightens targets regardless of
        favourable market conditions.
        """
        regime_mult = self.tp_scaler.get_tp_multiplier(
            regime=regime,
            atr_pct=atr_pct,
            adx=adx,
            win_streak=win_streak,
        )
        wr_adj = self.win_adjuster.get_tp_adjustment()
        combined = max(_TP_MULT_MIN, min(_TP_MULT_MAX, regime_mult * wr_adj))
        logger.debug(
            "[ProfitModeOptimizer] TP mult: regime×%.3f × wr_adj×%.3f = %.3f",
            regime_mult, wr_adj, combined,
        )
        return round(combined, 4)

    def record_trade_outcome(self, symbol: str, is_win: bool) -> None:
        """Record the result of a closed trade into the win-rate adjuster."""
        self.win_adjuster.record_outcome(is_win=is_win)

    def get_report(self) -> dict:
        """Return a combined status report from all three components."""
        return {
            "win_rate_adjuster": self.win_adjuster.get_report(),
            "pair_ranker":       self.pair_ranker.get_report(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton factory
# ─────────────────────────────────────────────────────────────────────────────

_pmo_instance: Optional[ProfitModeOptimizer] = None
_pmo_lock = threading.Lock()


def get_profit_mode_optimizer(win_rate_window: int = _WIN_RATE_WINDOW) -> ProfitModeOptimizer:
    """
    Return the process-wide singleton :class:`ProfitModeOptimizer`.

    On the first call the instance is created with the supplied parameters.
    Subsequent calls return the same object regardless of parameters.
    """
    global _pmo_instance
    if _pmo_instance is None:
        with _pmo_lock:
            if _pmo_instance is None:
                _pmo_instance = ProfitModeOptimizer(win_rate_window=win_rate_window)
    return _pmo_instance
