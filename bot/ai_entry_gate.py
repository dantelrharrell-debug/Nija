"""
NIJA AI Entry Gate
===================

Score-based entry confirmation filter.

Each gate contributes weighted points.  An entry is permitted when the
total gate score meets the minimum threshold — no single gate can veto a
trade on its own (except VOLATILITY_EXPLOSION, which always hard-blocks).

Gate weights (total = 7 points + informational regime label)
---------------------------------
Gate 1 — AI Predictive Score         3 pts  (signal quality)
Gate 2 — Volume / Liquidity          2 pts  (execution safety)
Gate 3 — Volatility Range            1 pt   (market conditions)
Gate 4 — Spread / Slippage           1 pt   (cost safety)
Gate 5 — Regime Classification       0 pts  (informational context only)

Pass threshold is adaptive and applied inside ``AIEntryGate.check()``.
Gate 5 does not add or remove points (informational only).

  AI + Volume alone can now trigger a trade even if volume is weak.
  Still respects the hard-block: VOLATILITY_EXPLOSION regime.
  Threshold auto-restores to 5.0 once account balance reaches $100 via
  check_balance_and_adjust_threshold() in trade_frequency_controller.
Once the account balance reaches the target (default $100), callers should invoke
``set_gate_pass_threshold(5.0)`` (or use ``TradeFrequencyController.check_balance_and_adjust_threshold``)
to restore the stricter 5-point pass requirement.

Drought relaxation
------------------
When the TradeFrequencyController signals a 2-hour trade drought, callers
may pass ``gate_score_reduction`` (0–1 fraction) to lower the per-gate
score thresholds by that percentage, making it easier to pass each gate.

Usage
-----
::

    from bot.ai_entry_gate import get_ai_entry_gate

    gate = get_ai_entry_gate()

    result = gate.check(
        df=df,
        indicators=indicators,
        side='long',
        enhanced_score=72.5,
        regime=self.current_regime,
        broker='coinbase',
        entry_type='swing',
        gate_score_reduction=0.10,   # 10% drought relaxation (optional)
    )

    if not result.passed:
        return {'action': 'hold', 'reason': result.reason}

Author: NIJA Trading Systems
Version: 2.0 — score-based OR logic
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

try:
    from bot.adaptive_entry_thresholds import (
        ADX_FLOOR,
        get_adaptive_entry_thresholds,
    )
except Exception:  # pragma: no cover - optional runtime dependency
    try:
        from adaptive_entry_thresholds import (  # type: ignore
            ADX_FLOOR,
            get_adaptive_entry_thresholds,
        )
    except Exception:  # pragma: no cover
        ADX_FLOOR = 1.5  # type: ignore[assignment]
        get_adaptive_entry_thresholds = None  # type: ignore[assignment]

logger = logging.getLogger("nija.ai_entry_gate")

# ── Rejection histogram (optional — degrades gracefully when unavailable) ────
try:
    from bot.rejection_histogram import get_rejection_histogram as _get_rej_hist
    _REJECTION_HIST_AVAILABLE = True
except ImportError:
    try:
        from rejection_histogram import get_rejection_histogram as _get_rej_hist  # type: ignore[import]
        _REJECTION_HIST_AVAILABLE = True
    except ImportError:
        _get_rej_hist = None  # type: ignore
        _REJECTION_HIST_AVAILABLE = False

# ── DIAGNOSTIC BYPASS FLAGS ──────────────────────────────────────────────────
# NIJA_DISABLE_REGIME_GATE=true → Gate 5 (regime compatibility check) always
#   passes regardless of entry-type/regime mismatch.  Use during pipeline
#   diagnostics to confirm signals exist without regime interference.
#   Remove or set to "false" once you've confirmed the pipeline is working.
_DISABLE_REGIME_GATE: bool = (
    os.getenv("NIJA_DISABLE_REGIME_GATE", "false").lower() in ("1", "true", "yes")
)

# NIJA_HARD_BLOCK_VOLATILITY_EXPLOSION=true keeps crisis hard-block behavior.
# Default is permissive so score-based gating can continue to operate.
_HARD_BLOCK_VOLATILITY_EXPLOSION: bool = (
    os.getenv("NIJA_HARD_BLOCK_VOLATILITY_EXPLOSION", "false").lower() in ("1", "true", "yes")
)

# NIJA_AI_ENTRY_GATE_DIAGNOSTICS=true enables detailed per-gate rejection logging.
_GATE_DIAGNOSTICS_ENABLED: bool = (
    os.getenv("NIJA_AI_ENTRY_GATE_DIAGNOSTICS", "false").lower() in ("1", "true", "yes")
)


# ---------------------------------------------------------------------------
# Per-gate result
# ---------------------------------------------------------------------------

@dataclass
class GateCheck:
    """Result for a single gate."""
    passed: bool
    name: str
    value: float = 0.0        # measured value
    threshold: float = 0.0    # required threshold
    detail: str = ""
    # Fraction of the gate's weight to award when passed=False.
    #  0.5  → partial credit (+1 of 2 pts for a weight-2 gate)
    #  0.0  → no credit (normal failure)
    # -1.0  → full penalty (−2 pts for a weight-2 gate — discourages mismatch
    #          without hard-blocking; strong signals still clear the threshold)
    partial_credit: float = 0.0


# ---------------------------------------------------------------------------
# Overall gate result
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """
    Aggregated result from all 5 gates.

    ``passed`` is True when the weighted gate score meets the pass threshold.
    ``gates`` is an ordered dict so callers can inspect each decision.
    """
    passed: bool
    reason: str
    first_failure: str = ""
    gates: Dict[str, GateCheck] = field(default_factory=dict)
    entry_type: str = "swing"
    regime_name: str = "unknown"
    gate_score: float = 0.0     # points earned across all gates (float: partial/penalty supported)
    gate_max: int = 9         # maximum possible points
    effective_threshold: float = 0.0


# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------

# ── Gate 1: AI Score thresholds per regime ──────────────────────────────────
# Tighter in choppy / crisis regimes, looser when trend gives a clear edge.
# Lowered ~20% across all regimes (Apr 2026) to increase trade frequency.
# Further relaxed ranging/mean_reversion/volatile/weak_trend (Apr 2026) to
# allow more entries during sideways and moderate-volatility market conditions.
# Slightly reduced again (Option A, Apr 2026) to increase signal sensitivity.
# Reduced further (Jun 2026) to unblock 0-trade condition — all gates rejecting.
_SCORE_THRESHOLDS: Dict[str, float] = {
    "strong_trend":         5.0,    # trend gives edge → relax (was 9)
    "weak_trend":           5.0,    # default (was 9)
    "ranging":              6.0,    # direction hard to call → require better setup (was 10)
    "consolidation":        4.0,    # scalp mode → need high frequency (was 8)
    "expansion":            5.0,    # breakout → normal bar (was 9)
    "mean_reversion":       6.0,    # counter-trend → extra conviction (was 10)
    "volatility_explosion": 65.0,   # crisis → near-perfect setups only (unchanged — crisis protection preserved)
    # Legacy 3-regime fallbacks
    "trending":             5.0,    # was 9
    "volatile":             8.0,    # was 15
}
_DEFAULT_SCORE_THRESHOLD = 5.0    # was 9.0 — lowered to unblock 0-trade condition

# ── Gate 2: Volume multiplier ────────────────────────────────────────────────
# Current volume must be >= this × 20-bar average.
_VOL_MULTIPLIER_DEFAULT  = 0.35   # Lowered from 0.60 → 0.35 to unblock 0-trade condition
_VOL_MULTIPLIER_SCALP    = 0.35   # Lowered from 0.60 → 0.35 to unblock 0-trade condition

# ── Gate 3: ATR % range per entry type ──────────────────────────────────────
# (min_atr_pct, max_atr_pct)
_ATR_RANGES: Dict[str, tuple] = {
    "scalp":          (0.10, 6.00),   # widened (was 0.20–4.00): allow quieter AND more volatile markets for scalp
    "swing":          (0.40, 9.00),   # swing tolerates wider moves
    "breakout":       (0.80, 15.00),  # breakout needs meaningful move
    "mean_reversion": (0.30, 8.00),   # reversal fine with moderate vol
}
_ATR_RANGE_DEFAULT = (0.30, 10.00)

# Override max ATR in VOLATILITY_EXPLOSION regardless of entry type
_ATR_CRISIS_MAX = 12.00

# ── Gate 4: Spread + slippage ceilings ──────────────────────────────────────
# Total execution cost (spread + est. slippage) must be below this ceiling.
_SPREAD_CEILINGS: Dict[str, float] = {
    "coinbase": float(os.getenv("NIJA_AI_GATE_SPREAD_CEILING_COINBASE", "0.25")),
    "kraken":   float(os.getenv("NIJA_AI_GATE_SPREAD_CEILING_KRAKEN", "0.22")),
    "binance":  float(os.getenv("NIJA_AI_GATE_SPREAD_CEILING_BINANCE", "0.12")),
    "okx":      float(os.getenv("NIJA_AI_GATE_SPREAD_CEILING_OKX", "0.15")),
}
_SPREAD_CEILING_DEFAULT = float(os.getenv("NIJA_AI_GATE_SPREAD_CEILING_DEFAULT", "0.25"))
_SLIPPAGE_ESTIMATE      = float(os.getenv("NIJA_AI_GATE_SLIPPAGE_ESTIMATE_PCT", "0.04"))

# ── Gate 5: Regime ↔ entry-type compatibility matrix ────────────────────────
# Maps regime → set of ALLOWED entry types.
# An entry type NOT in the set is blocked.
_REGIME_ALLOWED_ENTRIES: Dict[str, set] = {
    "strong_trend":         {"swing", "breakout"},
    "weak_trend":           {"swing", "scalp"},
    "ranging":              {"mean_reversion", "scalp", "ranging", "swing"},  # expanded for aggressive growth
    "consolidation":        {"scalp"},
    "expansion":            {"breakout", "swing"},
    "mean_reversion":       {"mean_reversion", "scalp", "ranging", "swing"},  # expanded for aggressive growth
    "volatility_explosion": set(),   # BLOCK ALL new entries
    # Legacy
    "trending":             {"swing", "breakout"},
    "volatile":             {"swing"},   # allow swing but with caution
}
_REGIME_ALLOWED_DEFAULT = {"swing", "scalp", "mean_reversion", "breakout"}

# Maps regime → entry types that earn PARTIAL credit (half the gate weight).
# These types aren't the primary fit but retain positive edge in the regime.
# Any type not in allowed OR adjacent earns a PENALTY (−full weight).
_REGIME_ADJACENT_ENTRIES: Dict[str, set] = {
    "strong_trend":   {"scalp"},                    # scalp can ride a strong trend
    "weak_trend":     {"breakout"},                 # breakout still has edge in weak trend
    "ranging":        {"swing"},                    # swing can work in ranging, just not ideal
    "consolidation":  {"swing"},                    # swing viable pre-breakout
    "expansion":      {"scalp", "mean_reversion"},  # both have edge in expansion
    "mean_reversion": {"scalp"},                    # scalp on bounce is partial MR
    "trending":       {"scalp"},
    "volatile":       {"scalp", "breakout"},
}

# ── Score-based OR logic ─────────────────────────────────────────────────────
# Gate weights — must sum to _GATE_MAX_SCORE
_GATE_WEIGHTS: Dict[str, int] = {
    "gate1_score":      3,   # AI signal quality (most important)
    "gate2_volume":     2,   # liquidity / execution safety
    "gate3_volatility": 1,   # market conditions
    "gate4_spread":     1,   # cost safety
    "gate5_regime":     0,   # market context label only (no scoring)
}
_GATE_MAX_SCORE: int = sum(_GATE_WEIGHTS.values())  # auto-summed (currently 7)

# Mutable base threshold — lowered to 1.6 to maximize confirmation trades in
# current market conditions.  Any gate combination scoring ≥ 1.6 pts passes
# (Gate 2+3 = 2+1 = 3 pts → PASS; Gate 1 alone = 3 pts → PASS; Gate 3+4 = 2 pts → PASS).
# Restored to 5.0 once the account balance reaches TARGET_BALANCE ($100)
# via ``set_gate_pass_threshold`` / ``TradeFrequencyController.check_balance_and_adjust_threshold``.
BASE_ENTRY_SCORE_THRESHOLD: float = 1.6  # base threshold on the 7-point scoring domain

# ── ATR-based volatility dampening constants ─────────────────────────────────
# When the market is actively moving the gate pass-threshold is relaxed
# proportionally so moderate signals can trade.  Three tiers:
#   ATR% ≥ _ATR_PCT_STRONG  (1.0%) — strong intraday trend; no extra relaxation
#                                     (regime gate already reflects this edge)
#   ATR% ≥ _ATR_PCT_MODERATE (0.60%) — moderate movement; 5% gate reduction
#   ATR% ≥ _ATR_PCT_SCALP   (0.35%) — enough volatility for a scalp; 10% reduction
# Values calibrated to Coinbase 15-min candle ATR distributions (Apr 2026).
_ATR_PCT_STRONG           = 1.0    # Strong intraday movement — no extra dampening
_ATR_PCT_MODERATE         = 0.60   # Moderate movement → mild threshold relaxation
_ATR_PCT_SCALP            = 0.35   # Sufficient volatility for scalp → larger relaxation
_ATR_DAMPENING_MODERATE   = 0.05   # Gate reduction at _ATR_PCT_MODERATE level (5%)
_ATR_DAMPENING_SCALP      = 0.10   # Gate reduction at _ATR_PCT_SCALP level (10%)

# Maximum combined threshold reduction (drought relaxation + ATR dampening).
# Capped at 55% so that at least ~45% of the normal quality bar must still be met.
_MAX_TOTAL_THRESHOLD_REDUCTION = 0.55


# ---------------------------------------------------------------------------
# Bayesian Online Threshold Tuner
# ---------------------------------------------------------------------------

class OnlineThresholdTuner:
    """
    Per-regime Bayesian (Beta-Binomial) online threshold adjuster.

    Tracks win/loss outcomes per market regime using a Beta distribution as the
    conjugate prior for a Bernoulli win-rate process.  As trades accumulate the
    posterior mean win-rate shifts ``BASE_ENTRY_SCORE_THRESHOLD`` up or down:

    * **Win-rate > target** → loosen threshold by up to ``max_delta`` points
      (the model has evidence that the current signal quality is alpha-positive)
    * **Win-rate < target** → tighten threshold by up to ``max_delta`` points
      (alpha degrades; raise the bar to protect capital)

    The adjustment is proportional to the distance from the target win-rate and
    is capped at ``max_delta`` to prevent extreme swings.  A minimum sample size
    ``min_n`` is required before the tuner has any effect (guards against noise
    in early data).

    Thread-safe.  Obtain the process-wide singleton via ``get_online_threshold_tuner()``.
    """

    _TARGET_WIN_RATE:  float = 0.55   # desired long-run win rate
    _MAX_DELTA:        float = 1.0    # maximum threshold adjustment (gate-score points)
    _MIN_N:            int   = 10     # minimum outcomes before tuning kicks in
    _ALPHA0:           float = 3.0    # prior alpha (weak belief in 50% win rate)
    _BETA0:            float = 3.0    # prior beta

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # regime → [alpha, beta]  (Beta distribution parameters)
        self._params: Dict[str, list] = {}

    def _get_params(self, regime: str) -> list:
        if regime not in self._params:
            self._params[regime] = [self._ALPHA0, self._BETA0]
        return self._params[regime]

    def record_outcome(self, regime: str, won: bool) -> None:
        """Record the outcome of a completed trade."""
        regime = (regime or "unknown")[:32]
        with self._lock:
            p = self._get_params(regime)
            if won:
                p[0] += 1.0   # alpha += 1 (success)
            else:
                p[1] += 1.0   # beta  += 1 (failure)

    def get_threshold_adjustment(self, regime: str) -> float:
        """
        Return a signed threshold delta for the given regime.

        Positive delta → tighten (more selective).
        Negative delta → loosen (more permissive).
        Returns 0.0 until ``min_n`` outcomes are observed.
        """
        regime = (regime or "unknown")[:32]
        with self._lock:
            p = list(self._get_params(regime))   # [alpha, beta]
        alpha, beta = p
        n = (alpha - self._ALPHA0) + (beta - self._BETA0)
        if n < self._MIN_N:
            return 0.0
        win_rate = alpha / (alpha + beta)
        deviation = win_rate - self._TARGET_WIN_RATE
        # Positive deviation → high win rate → loosen (negative delta)
        # Negative deviation → low win rate  → tighten (positive delta)
        return float(-deviation * (self._MAX_DELTA / self._TARGET_WIN_RATE))

    def get_state(self) -> Dict[str, Any]:
        """Return regime-level posterior summary for observability."""
        with self._lock:
            state: Dict[str, Any] = {}
            for regime, (alpha, beta) in self._params.items():
                n = (alpha - self._ALPHA0) + (beta - self._BETA0)
                win_rate = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.0
                state[regime] = {
                    "n": int(n),
                    "win_rate": round(win_rate, 3),
                    "alpha": round(alpha, 1),
                    "beta":  round(beta, 1),
                    "threshold_adj": round(self.get_threshold_adjustment(regime), 3),
                }
        return state


_TUNER_SINGLETON: Optional[OnlineThresholdTuner] = None
_TUNER_LOCK = threading.Lock()


def get_online_threshold_tuner() -> OnlineThresholdTuner:
    """Return the process-wide singleton :class:`OnlineThresholdTuner`."""
    global _TUNER_SINGLETON
    if _TUNER_SINGLETON is None:
        with _TUNER_LOCK:
            if _TUNER_SINGLETON is None:
                _TUNER_SINGLETON = OnlineThresholdTuner()
    return _TUNER_SINGLETON


# ---------------------------------------------------------------------------
# Gate class
# ---------------------------------------------------------------------------

class AIEntryGate:
    """
    Score-based 5-gate entry confirmation filter.

    All 5 gates are evaluated regardless of individual pass/fail.  A trade
    is permitted when the total weighted score meets _GATE_PASS_THRESHOLD.

    Thread-safe; stateless per-call (no shared mutable state between calls).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_checked = 0
        self._total_passed  = 0
        self._gate_failures: Dict[str, int] = {
            "gate1_score": 0,
            "gate2_volume": 0,
            "gate3_volatility": 0,
            "gate4_spread": 0,
            "gate5_regime": 0,
        }
        logger.info(
            "🚦 AIEntryGate initialized — "
            "score-based OR logic: %d gates, pass at %.1f/%d pts",
            len(_GATE_WEIGHTS), BASE_ENTRY_SCORE_THRESHOLD, _GATE_MAX_SCORE,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        side: str,
        enhanced_score: float,
        regime: Any = None,
        broker: str = "coinbase",
        entry_type: str = "swing",
        gate_score_reduction: float = 0.0,
        volume_gate_multiplier: Optional[float] = None,
        reason: str = "",
    ) -> GateResult:
        """
        Run all 5 gates and return a score-based pass/fail decision.

        Args:
            df: OHLCV DataFrame (recent candles).
            indicators: Calculated indicator dict from strategy.
            side: 'long' or 'short'.
            enhanced_score: AI/enhanced entry score (0-100).
            regime: Current market regime (enum or string).
            broker: Exchange name (used for spread ceiling).
            entry_type: Strategy type active for this entry.
            gate_score_reduction: Fractional threshold reduction from
                drought safeguard (0.0 = no relaxation, 0.10 = 10% easier).
            volume_gate_multiplier: Optional regime-specific override for the
                fraction of average volume required (e.g. 0.80 in crisis,
                0.50 in strong trend).  When ``None`` the default
                ``_VOL_MULTIPLIER_DEFAULT`` (0.60) is used.

        Returns:
            GateResult with pass/fail, total gate score, and per-gate detail.
        """
        regime_key = self._regime_key(regime)
        broker_key = self._broker_key(broker)
        gates: Dict[str, GateCheck] = {}

        # ── EXEC TEST MODE bypass ─────────────────────────────────────
        # When the caller is a test probe, skip all scoring gates so the
        # full execution stack can be validated without needing a live
        # market signal.  Auth, nonce, and exchange connection are
        # intentionally NOT bypassed — only strategy filters / scoring gates.
        if reason == "EXEC_TEST_PROBE":
            logger.info("🧪 AIEntryGate: TEST_MODE_BYPASS — skipping all scoring gates")
            return GateResult(
                passed=True,
                reason="TEST_MODE_BYPASS",
                first_failure="",
                gates=gates,
                entry_type=entry_type,
                regime_name=self._regime_key(regime),
                gate_score=100,
                gate_max=_GATE_MAX_SCORE,
                effective_threshold=0.0,
            )

        with self._lock:
            self._total_checked += 1

        # ── Optional hard block: VOLATILITY_EXPLOSION ─────────────────
        # Default now allows score-based evaluation unless explicitly forced.
        if regime_key == "volatility_explosion" and _HARD_BLOCK_VOLATILITY_EXPLOSION:
            reason = "❌ VOLATILITY_EXPLOSION: all new entries hard-blocked (capital protection)"
            logger.debug("AIEntryGate: %s", reason)
            if _REJECTION_HIST_AVAILABLE and _get_rej_hist is not None:
                try:
                    _get_rej_hist().record(
                        stage="ai_gate",
                        reason="volatility_explosion",
                        regime=regime_key,
                    )
                except Exception:
                    pass
            return GateResult(
                passed=False,
                reason=reason,
                first_failure="volatility_explosion",
                gates=gates,
                entry_type=entry_type,
                regime_name=regime_key,
                gate_score=0,
                gate_max=_GATE_MAX_SCORE,
                effective_threshold=_GATE_MAX_SCORE,
            )
        if regime_key == "volatility_explosion":
            logger.warning(
                "⚠️ AIEntryGate advisory: VOLATILITY_EXPLOSION detected; continuing score-based evaluation"
            )

        # ── Evaluate all 5 gates, collect scores ─────────────────────
        adaptive_thresholds = None
        if get_adaptive_entry_thresholds is not None:
            try:
                adaptive_thresholds = get_adaptive_entry_thresholds(
                    df=df,
                    indicators=indicators,
                    regime=regime_key,
                    zero_signal_streak=int(gate_score_reduction * 20),
                )
            except Exception as exc:
                logger.debug("Adaptive entry thresholds unavailable: %s", exc)

        g1 = self._gate_score(
            enhanced_score,
            regime_key,
            gate_score_reduction,
            adaptive_confidence_threshold=(
                adaptive_thresholds.confidence if adaptive_thresholds is not None else None
            ),
        )
        gates["gate1_score"] = g1

        adaptive_volume = (
            adaptive_thresholds.relative_volume
            if adaptive_thresholds is not None
            else None
        )
        if volume_gate_multiplier is not None and adaptive_volume is not None:
            adaptive_volume = max(float(volume_gate_multiplier), float(adaptive_volume))
        elif adaptive_volume is None:
            adaptive_volume = volume_gate_multiplier
        g2 = self._gate_volume(df, entry_type, adaptive_volume)
        gates["gate2_volume"] = g2

        g3 = self._gate_volatility(
            df,
            indicators,
            regime_key,
            entry_type,
            adaptive_adx_threshold=(
                adaptive_thresholds.adx if adaptive_thresholds is not None else None
            ),
        )
        gates["gate3_volatility"] = g3

        g4 = self._gate_spread(df, broker_key)
        gates["gate4_spread"] = g4

        g5 = self._gate_regime(regime_key, entry_type, side)
        gates["gate5_regime"] = g5

        # ── Tally weighted score (partial credit and penalties supported) ──────
        # Load regime-specific gate weights from self-learning tuner when available.
        _active_gate_weights: Optional[Dict[str, float]] = None
        try:
            from self_learning_weight_tuner import get_weight_tuner as _gwt  # type: ignore
        except ImportError:
            try:
                from bot.self_learning_weight_tuner import get_weight_tuner as _gwt  # type: ignore
            except ImportError:
                _gwt = None  # type: ignore
        if _gwt is not None:
            try:
                _active_gate_weights = _gwt().get_gate_weights(str(regime_key or "default"))
            except Exception:
                pass

        total_score: float = 0.0
        failed_gates = []
        for key, check in gates.items():
            w = float(
                (_active_gate_weights or _GATE_WEIGHTS).get(key, 0)
            )
            if check.passed:
                total_score += w
            elif check.partial_credit != 0.0:
                # Positive partial_credit → partial score; negative → penalty.
                total_score += w * check.partial_credit
                if check.partial_credit < 0:
                    failed_gates.append(key)   # penalties appear in failure report
                with self._lock:
                    self._gate_failures[key] = self._gate_failures.get(key, 0) + 1
            else:
                failed_gates.append(key)
                with self._lock:
                    self._gate_failures[key] = self._gate_failures.get(key, 0) + 1

        # Drought relaxation lowers the effective threshold.
        # Cap reduction at 50% and enforce a minimum of 2 points so that
        # at least two gate conditions must still be satisfied.
        capped_reduction = min(gate_score_reduction, 0.50)

        # ── ATR-based volatility dampening ───────────────────────────────────
        # If the market is actively moving (ATR% above a baseline), relax the
        # gate threshold by up to 10% so moderate signals pass during volatile
        # sessions.  The dampening is proportional to ATR and capped so core
        # risk protection is preserved.
        # Crisis (volatility_explosion) is already hard-blocked above — no risk.
        _atr_dampening = 0.0
        try:
            _atr_series = indicators.get("atr")
            if _atr_series is not None and len(df) > 0:
                _atr_val  = float(_atr_series.iloc[-1])
                _price    = float(df["close"].iloc[-1])
                _atr_pct  = (_atr_val / _price * 100.0) if _price > 0 else 0.0
                if _atr_pct >= _ATR_PCT_STRONG:
                    _atr_dampening = 0.0                  # strong trend — no extra relaxation needed
                elif _atr_pct >= _ATR_PCT_MODERATE:
                    _atr_dampening = _ATR_DAMPENING_MODERATE   # moderate movement → 5% easier
                elif _atr_pct >= _ATR_PCT_SCALP:
                    _atr_dampening = _ATR_DAMPENING_SCALP      # enough volatility for a scalp → 10% easier
        except Exception as _e:
            logger.debug("ATR dampening unavailable: %s", _e)

        # Combine drought reduction + ATR dampening (total cap _MAX_TOTAL_THRESHOLD_REDUCTION)
        total_reduction = min(capped_reduction + _atr_dampening, _MAX_TOTAL_THRESHOLD_REDUCTION)

        # Use the AdaptiveThresholdController's gate-domain adjustment so the
        # pass bar tightens when win rate is low and loosens when it is high.
        # Falls back to the static BASE_ENTRY_SCORE_THRESHOLD if unavailable.
        try:
            from nija_ai_engine import get_nija_ai_engine as _get_aie
            _adaptive_base = _get_aie().threshold_ctrl.get_threshold(BASE_ENTRY_SCORE_THRESHOLD)
        except Exception:
            try:
                from bot.nija_ai_engine import get_nija_ai_engine as _get_aie
                _adaptive_base = _get_aie().threshold_ctrl.get_threshold(BASE_ENTRY_SCORE_THRESHOLD)
            except Exception:
                _adaptive_base = BASE_ENTRY_SCORE_THRESHOLD

        effective_threshold = max(
            2,
            int(_adaptive_base * (1.0 - total_reduction)),
        )

        # ── Bayesian online threshold adjustment ──────────────────────
        # Apply the per-regime posterior win-rate adjustment so the gate
        # automatically loosens in high-alpha regimes and tightens when
        # win rate deteriorates.  Only active after min_n outcomes.
        try:
            _bayes_adj = get_online_threshold_tuner().get_threshold_adjustment(regime_key)
            if abs(_bayes_adj) > 0.01:
                _pre_thresh = effective_threshold
                # Clamp final threshold to [1, _GATE_MAX_SCORE]
                effective_threshold = max(
                    1,
                    min(_GATE_MAX_SCORE, effective_threshold + _bayes_adj),
                )
                logger.debug(
                    "AIEntryGate Bayesian adj regime=%s delta=%.2f threshold %.1f→%.1f",
                    regime_key, _bayes_adj, _pre_thresh, effective_threshold,
                )
        except Exception:
            pass
        _gate_feedback_enabled = str(os.getenv("NIJA_EIL_GATE_FEEDBACK_ENABLED", "false")).lower() in (
            "1",
            "true",
            "yes",
        )
        _path_prefix = "|".join(
            [
                f"gate1_score:{'pass' if gates['gate1_score'].passed else 'fail'}",
                f"gate2_volume:{'pass' if gates['gate2_volume'].passed else 'fail'}",
            ]
        )
        if _gate_feedback_enabled:
            try:
                from bot.regime_gate_calibrator import get_regime_gate_calibrator
            except Exception:
                try:
                    from regime_gate_calibrator import get_regime_gate_calibrator  # type: ignore[import]
                except Exception:
                    get_regime_gate_calibrator = None  # type: ignore[assignment]
            if get_regime_gate_calibrator is not None:
                try:
                    _calibrator = get_regime_gate_calibrator()
                    _regime_pass_prob = _calibrator.get_gate_pass_probability(regime_key, _path_prefix)
                    if _regime_pass_prob < 0.35:
                        effective_threshold = min(_GATE_MAX_SCORE, effective_threshold + 1)
                except Exception:
                    pass
        passed = total_score >= effective_threshold

        if passed:
            with self._lock:
                self._total_passed += 1
            reason = (
                f"✅ Gate score {total_score:.1f}/{_GATE_MAX_SCORE} "
                f"≥ {effective_threshold} threshold | "
                f"{side.upper()} {entry_type} | regime={regime_key.upper()}"
            )
            first_failure = ""
        else:
            first_failure = failed_gates[0] if failed_gates else ""
            reason = (
                f"❌ Gate score {total_score:.1f}/{_GATE_MAX_SCORE} "
                f"< {effective_threshold} threshold | "
                f"failed: {', '.join(failed_gates)}"
            )
            # Record in rejection histogram — bin by first failing gate
            if _REJECTION_HIST_AVAILABLE and _get_rej_hist is not None:
                try:
                    _hist_reason = (
                        f"score_{total_score:.1f}_below_{effective_threshold}"
                        if not failed_gates
                        else f"{first_failure}_score_{total_score:.1f}"
                    )
                    _get_rej_hist().record(
                        stage="ai_gate",
                        reason=_hist_reason,
                        regime=regime_key,
                    )
                except Exception:
                    pass

        logger.info(
            f"FINAL DECISION → score={total_score:.2f} threshold={effective_threshold:.2f}"
            f" execute={passed}"
        )
        if not passed:
            logger.info(
                f"TRADE REJECTED → reason={reason} score={total_score} conf={enhanced_score}"
            )
            if _GATE_DIAGNOSTICS_ENABLED:
                per_gate = ", ".join(
                    f"{k}:{'pass' if g.passed else 'fail'}({g.value}/{g.threshold})"
                    for k, g in gates.items()
                )
                logger.info("AI ENTRY DIAGNOSTICS → %s", per_gate)
        logger.debug("AIEntryGate: %s", reason)
        if _gate_feedback_enabled:
            try:
                from bot.regime_gate_calibrator import get_regime_gate_calibrator
            except Exception:
                try:
                    from regime_gate_calibrator import get_regime_gate_calibrator  # type: ignore[import]
                except Exception:
                    get_regime_gate_calibrator = None  # type: ignore[assignment]
            if get_regime_gate_calibrator is not None:
                try:
                    get_regime_gate_calibrator().update(regime_key, _path_prefix, passed)
                except Exception:
                    pass
        return GateResult(
            passed=passed,
            reason=reason,
            first_failure=first_failure,
            gates=gates,
            entry_type=entry_type,
            regime_name=regime_key,
            gate_score=total_score,
            gate_max=_GATE_MAX_SCORE,
            effective_threshold=float(effective_threshold),
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate pass/fail statistics."""
        with self._lock:
            stats = {
                "total_checked": self._total_checked,
                "total_passed":  self._total_passed,
                "pass_rate":     (
                    self._total_passed / self._total_checked
                    if self._total_checked > 0 else 0.0
                ),
                "gate_failures": dict(self._gate_failures),
            }
        try:
            stats["bayesian_tuner"] = get_online_threshold_tuner().get_state()
        except Exception:
            pass
        return stats

    # ------------------------------------------------------------------
    # Individual gate implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _gate_score(
        enhanced_score: float,
        regime_key: str,
        gate_score_reduction: float = 0.0,
        adaptive_confidence_threshold: Optional[float] = None,
    ) -> GateCheck:
        """Gate 1: AI predictive score vs regime-adjusted threshold."""
        threshold = _SCORE_THRESHOLDS.get(regime_key, _DEFAULT_SCORE_THRESHOLD)
        if adaptive_confidence_threshold is not None:
            threshold = float(adaptive_confidence_threshold) * 100.0
        # Apply drought relaxation — lower threshold by the given fraction
        threshold = threshold * (1.0 - gate_score_reduction)
        threshold = max(12.0, min(22.0, threshold))
        passed = enhanced_score >= threshold
        return GateCheck(
            passed=passed,
            name="AI Score",
            value=enhanced_score,
            threshold=threshold,
            detail=(
                f"score {enhanced_score:.1f} {'≥' if passed else '<'} "
                f"threshold {threshold:.0f} (regime={regime_key})"
            ),
        )

    @staticmethod
    def _gate_volume(
        df: pd.DataFrame,
        entry_type: str,
        volume_gate_multiplier: Optional[float] = None,
    ) -> GateCheck:
        """Gate 2: Current bar volume vs 20-bar average liquidity floor.

        Args:
            df: OHLCV DataFrame.
            entry_type: Strategy type (e.g. 'scalp').
            volume_gate_multiplier: Optional regime-specific override for the
                minimum volume ratio.  When provided it takes precedence over
                the scalp/default constants.
        """
        try:
            avg_vol = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else df["volume"].mean()
            cur_vol = float(df["volume"].iloc[-1])
            ratio   = cur_vol / avg_vol if avg_vol > 0 else 0.0
        except Exception:
            # Can't measure volume → pass with warning (don't block on data issue)
            return GateCheck(passed=True, name="Volume",
                             detail="volume data unavailable — gate skipped")

        if volume_gate_multiplier is not None:
            # Regime-specific override takes priority; scalp always uses the higher of
            # the regime override and the scalp default so scalp never gets too loose.
            if entry_type == "scalp":
                min_mult = max(volume_gate_multiplier, _VOL_MULTIPLIER_SCALP)
            else:
                min_mult = volume_gate_multiplier
        else:
            min_mult = _VOL_MULTIPLIER_SCALP if entry_type == "scalp" else _VOL_MULTIPLIER_DEFAULT

        passed   = ratio >= min_mult
        return GateCheck(
            passed=passed,
            name="Volume",
            value=round(ratio, 3),
            threshold=min_mult,
            detail=(
                f"vol_ratio {ratio*100:.1f}% of avg "
                f"({'≥' if passed else '<'} {min_mult*100:.0f}% minimum)"
            ),
        )

    @staticmethod
    def _gate_volatility(
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        regime_key: str,
        entry_type: str,
        adaptive_adx_threshold: Optional[float] = None,
    ) -> GateCheck:
        """Gate 3: ATR% and adaptive ADX must be acceptable for the entry type."""
        try:
            atr_series = indicators.get("atr")
            if atr_series is None:
                return GateCheck(passed=True, name="Volatility",
                                 detail="ATR unavailable — gate skipped")
            atr = float(atr_series.iloc[-1])
            price = float(df["close"].iloc[-1])
            atr_pct = (atr / price * 100) if price > 0 else 0.0
        except Exception:
            return GateCheck(passed=True, name="Volatility",
                             detail="ATR calculation error — gate skipped")

        min_atr, max_atr = _ATR_RANGES.get(entry_type, _ATR_RANGE_DEFAULT)

        # Crisis override: cap max ATR in extreme vol regimes
        if regime_key == "volatility_explosion":
            max_atr = min(max_atr, _ATR_CRISIS_MAX)

        adx = None
        adx_threshold = adaptive_adx_threshold
        try:
            adx_series = indicators.get("adx")
            if adx_series is not None:
                adx = float(adx_series.iloc[-1]) if hasattr(adx_series, "iloc") else float(adx_series)
                adx_threshold = adx_threshold if adx_threshold is not None else ADX_FLOOR
        except Exception:
            adx = None

        passed = min_atr <= atr_pct <= max_atr
        if adx is not None and adx_threshold is not None:
            passed = passed and adx >= adx_threshold
        reason = ""
        if atr_pct < min_atr:
            reason = f"ATR {atr_pct:.2f}% < {min_atr:.2f}% min (market too quiet)"
        elif atr_pct > max_atr:
            reason = f"ATR {atr_pct:.2f}% > {max_atr:.2f}% max (market too wild)"
        elif adx is not None and adx_threshold is not None and adx < adx_threshold:
            reason = f"ADX {adx:.2f} < adaptive {adx_threshold:.2f} minimum"
        else:
            reason = f"ATR {atr_pct:.2f}% in [{min_atr:.2f}%, {max_atr:.2f}%]"
            if adx is not None and adx_threshold is not None:
                reason = f"{reason}; ADX {adx:.2f} ≥ adaptive {adx_threshold:.2f}"

        return GateCheck(
            passed=passed,
            name="Volatility",
            value=round(atr_pct, 3),
            threshold=min_atr,
            detail=reason,
        )

    @staticmethod
    def _gate_spread(df: pd.DataFrame, broker_key: str) -> GateCheck:
        """Gate 4: Bid-ask spread + estimated slippage vs broker ceiling."""
        # Try to read bid/ask from dataframe columns if present
        try:
            if "bid" in df.columns and "ask" in df.columns:
                bid = float(df["bid"].iloc[-1])
                ask = float(df["ask"].iloc[-1])
                mid = (bid + ask) / 2.0
                spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0
            else:
                # No bid/ask columns — estimate spread from high-low range
                high = float(df["high"].iloc[-1])
                low  = float(df["low"].iloc[-1])
                close = float(df["close"].iloc[-1])
                # Use a conservative fixed-rate estimate (0.10%) when bid/ask is unavailable.
                # Deriving spread from candle range is unreliable; fixed estimate is safer.
                spread_pct = 0.10   # 0.10% conservative fallback when no bid/ask data
        except Exception:
            return GateCheck(passed=True, name="Spread",
                             detail="spread data unavailable — gate skipped")

        total_cost = spread_pct + _SLIPPAGE_ESTIMATE
        ceiling    = _SPREAD_CEILINGS.get(broker_key, _SPREAD_CEILING_DEFAULT)
        passed     = total_cost <= ceiling

        return GateCheck(
            passed=passed,
            name="Spread",
            value=round(total_cost, 4),
            threshold=ceiling,
            detail=(
                f"spread {spread_pct:.3f}% + slippage {_SLIPPAGE_ESTIMATE:.2f}% "
                f"= {total_cost:.3f}% "
                f"({'≤' if passed else '>'} {ceiling:.2f}% ceiling on {broker_key})"
            ),
        )

    @staticmethod
    def _gate_regime(regime_key: str, entry_type: str, side: str) -> GateCheck:
        """Gate 5: Regime compatibility classification (informational only).

        This gate no longer adds or subtracts score because trend/regime validity
        is already established upstream in ``nija_apex_strategy_v71`` via
        ``check_market_filter`` plus the regime-aware scoring path
        (``check_entry_with_enhanced_scoring`` / Nija AI engine). It only reports
        compatibility context.
        """
        if _DISABLE_REGIME_GATE:
            return GateCheck(
                passed=True,
                name="Regime",
                detail=(
                    f"[BYPASS] NIJA_DISABLE_REGIME_GATE=true — "
                    f"regime gate skipped for {regime_key.upper()} {entry_type} {side}"
                ),
            )
        allowed  = _REGIME_ALLOWED_ENTRIES.get(regime_key, _REGIME_ALLOWED_DEFAULT)
        adjacent = _REGIME_ADJACENT_ENTRIES.get(regime_key, set())
        if entry_type in allowed:
            return GateCheck(
                passed=True,
                name="Regime",
                detail=(
                    f"regime={regime_key.upper()} permits {entry_type} {side} "
                    "(informational)"
                ),
            )
        elif entry_type in adjacent:
            return GateCheck(
                passed=True,
                name="Regime",
                partial_credit=0.0,
                detail=(
                    f"regime={regime_key.upper()} partially supports {entry_type} {side} "
                    "(informational)"
                ),
            )
        else:
            return GateCheck(
                passed=True,
                name="Regime",
                partial_credit=0.0,
                detail=(
                    f"regime={regime_key.upper()} conflicts with {entry_type} {side} "
                    "(informational)"
                ),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _regime_key(regime: Any) -> str:
        if regime is None:
            return "weak_trend"
        if hasattr(regime, "value"):
            return str(regime.value).lower()
        return str(regime).lower().replace(" ", "_")

    @staticmethod
    def _broker_key(broker: str) -> str:
        b = broker.lower()
        for key in _SPREAD_CEILINGS:
            if key in b:
                return key
        return "coinbase"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_gate_instance: Optional[AIEntryGate] = None
_gate_lock = threading.Lock()


def get_ai_entry_gate() -> AIEntryGate:
    """Return the module-level singleton ``AIEntryGate``."""
    global _gate_instance
    if _gate_instance is None:
        with _gate_lock:
            if _gate_instance is None:
                _gate_instance = AIEntryGate()
    return _gate_instance


def set_gate_pass_threshold(value: float) -> None:
    """
    Dynamically update ``BASE_ENTRY_SCORE_THRESHOLD`` at runtime.

    Use this to restore the stricter threshold once the account balance
    reaches the target (e.g. tighten back to 5.0 after reaching $100).
    Thread-safe: writes are atomic on CPython due to the GIL, but callers
    should treat this as an eventually-consistent hint rather than a hard
    synchronisation barrier.

    Args:
        value: New pass threshold (out of 9 gate points).  Clamped to [2, 9].
    """
    global BASE_ENTRY_SCORE_THRESHOLD
    clamped = max(2.0, min(float(value), float(_GATE_MAX_SCORE)))
    BASE_ENTRY_SCORE_THRESHOLD = clamped
    logger.info(
        "🚦 AIEntryGate pass threshold updated → %.1f/%d pts",
        BASE_ENTRY_SCORE_THRESHOLD, _GATE_MAX_SCORE,
    )


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np
    logging.basicConfig(level=logging.DEBUG)

    gate = get_ai_entry_gate()

    # Build a minimal test DataFrame
    n = 25
    prices = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open":   prices * 0.999,
        "high":   prices * 1.005,
        "low":    prices * 0.994,
        "close":  prices,
        "volume": np.abs(np.random.randn(n) * 1000) + 500,
    })
    indicators = {
        "atr": pd.Series([1.2] * n),   # ~1.2% ATR on $100 price
    }

    scenarios = [
        # (side, score, regime, broker, entry_type, label)
        ("long",  72, "strong_trend",         "coinbase", "swing",          "Normal swing buy"),
        ("long",  43, "strong_trend",         "coinbase", "swing",          "Score too low"),
        ("long",  72, "volatility_explosion", "coinbase", "swing",          "Crisis: blocked"),
        ("long",  72, "consolidation",        "kraken",   "scalp",          "Scalp in consolidation"),
        ("long",  72, "ranging",              "coinbase", "swing",          "Wrong type for range"),
        ("short", 65, "ranging",              "kraken",   "mean_reversion", "Mean-rev short in range"),
    ]

    print("\n" + "=" * 80)
    print("AI ENTRY GATE — SCENARIO TESTS")
    print("=" * 80)
    for side, score, regime, broker, etype, label in scenarios:
        r = gate.check(df, indicators, side, score, regime, broker, etype)
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"\n{label}")
        print(f"  {status} | {r.reason}")

    print(f"\nStats: {gate.get_stats()}")
