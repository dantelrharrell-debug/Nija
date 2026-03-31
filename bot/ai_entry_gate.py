"""
NIJA AI Entry Gate
===================

Score-based entry confirmation filter.

Each gate contributes weighted points.  An entry is permitted when the
total gate score meets the minimum threshold — no single gate can veto a
trade on its own (except VOLATILITY_EXPLOSION, which always hard-blocks).

Gate weights (total = 9 points)
---------------------------------
Gate 1 — AI Predictive Score         3 pts  (signal quality)
Gate 2 — Volume / Liquidity          2 pts  (execution safety)
Gate 3 — Volatility Range            1 pt   (market conditions)
Gate 4 — Spread / Slippage           1 pt   (cost safety)
Gate 5 — Regime Confirmation         2 pts  (market context)

Pass threshold: 3.5 / 9 (≈ 39 %, temporarily loosened for more trades).  This means:
  - Gate 1 alone                   → 3 pts → PASS  (AI score sufficient)
  - Gate 1 + Gate 2                → 5 pts → PASS
  - Gate 2 + Gate 3 + Gate 4      → 4 pts → PASS  (volume + conditions)
  - Gate 2 + Gate 3 + Gate 4 + Gate 5 → 6 pts → PASS (even without perfect AI score)

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
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger("nija.ai_entry_gate")


# ---------------------------------------------------------------------------
# Per-gate result
# ---------------------------------------------------------------------------

@dataclass
class GateCheck:
    """Result for a single gate."""
    passed: bool
    name: str
    value: float = 0.0       # measured value
    threshold: float = 0.0   # required threshold
    detail: str = ""


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
    gate_score: int = 0       # points earned across all gates
    gate_max: int = 9         # maximum possible points


# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------

# ── Gate 1: AI Score thresholds per regime ──────────────────────────────────
# Tighter in choppy / crisis regimes, looser when trend gives a clear edge.
_SCORE_THRESHOLDS: Dict[str, float] = {
    "strong_trend":         52.0,   # trend gives edge → relax slightly
    "weak_trend":           55.0,   # default
    "ranging":              62.0,   # direction hard to call → require better setup
    "consolidation":        45.0,   # scalp mode → need high frequency
    "expansion":            55.0,   # breakout → normal bar
    "mean_reversion":       60.0,   # counter-trend → extra conviction
    "volatility_explosion": 78.0,   # crisis → near-perfect setups only
    # Legacy 3-regime fallbacks
    "trending":             52.0,
    "volatile":             70.0,
}
_DEFAULT_SCORE_THRESHOLD = 55.0

# ── Gate 2: Volume multiplier ────────────────────────────────────────────────
# Current volume must be >= this × 20-bar average.
_VOL_MULTIPLIER_DEFAULT  = 0.60   # 60% of average (standard)
_VOL_MULTIPLIER_SCALP    = 0.80   # scalp needs tighter liquidity floor

# ── Gate 3: ATR % range per entry type ──────────────────────────────────────
# (min_atr_pct, max_atr_pct)
_ATR_RANGES: Dict[str, tuple] = {
    "scalp":          (0.20, 4.00),   # scalp needs tight vol
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
    "coinbase": 0.20,   # 0.20% (1.4% fee broker; wider spread hurts less)
    "kraken":   0.12,   # 0.12% (0.36% fee broker; spread matters more)
    "binance":  0.10,   # 0.10%
    "okx":      0.12,
}
_SPREAD_CEILING_DEFAULT = 0.20
_SLIPPAGE_ESTIMATE      = 0.05   # 0.05% estimated market slippage

# ── Gate 5: Regime ↔ entry-type compatibility matrix ────────────────────────
# Maps regime → set of ALLOWED entry types.
# An entry type NOT in the set is blocked.
_REGIME_ALLOWED_ENTRIES: Dict[str, set] = {
    "strong_trend":         {"swing", "breakout"},
    "weak_trend":           {"swing", "scalp"},
    "ranging":              {"mean_reversion", "scalp"},
    "consolidation":        {"scalp"},
    "expansion":            {"breakout", "swing"},
    "mean_reversion":       {"mean_reversion"},
    "volatility_explosion": set(),   # BLOCK ALL new entries
    # Legacy
    "trending":             {"swing", "breakout"},
    "volatile":             {"swing"},   # allow swing but with caution
}
_REGIME_ALLOWED_DEFAULT = {"swing", "scalp", "mean_reversion", "breakout"}

# ── Score-based OR logic ─────────────────────────────────────────────────────
# Gate weights — must sum to _GATE_MAX_SCORE
_GATE_WEIGHTS: Dict[str, int] = {
    "gate1_score":      3,   # AI signal quality (most important)
    "gate2_volume":     2,   # liquidity / execution safety
    "gate3_volatility": 1,   # market conditions
    "gate4_spread":     1,   # cost safety
    "gate5_regime":     2,   # market context
}
_GATE_MAX_SCORE: int = sum(_GATE_WEIGHTS.values())  # 9

# Temporarily loosened from 5.0 → 3.5 to allow more trades.
# AI score gate alone (3 pts) is now sufficient to pass.
# Restored to 5.0 once the account balance reaches TARGET_BALANCE ($100)
# via ``set_gate_pass_threshold`` / ``TradeFrequencyController.check_balance_and_adjust_threshold``.
BASE_ENTRY_SCORE_THRESHOLD: float = 3.5  # out of 9 — temporarily loosened for more trades


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

        Returns:
            GateResult with pass/fail, total gate score, and per-gate detail.
        """
        regime_key = self._regime_key(regime)
        broker_key = self._broker_key(broker)
        gates: Dict[str, GateCheck] = {}

        with self._lock:
            self._total_checked += 1

        # ── Hard block: VOLATILITY_EXPLOSION ─────────────────────────
        # Capital preservation always wins — no scoring bypass.
        if regime_key == "volatility_explosion":
            reason = "❌ VOLATILITY_EXPLOSION: all new entries hard-blocked (capital protection)"
            logger.debug("AIEntryGate: %s", reason)
            return GateResult(
                passed=False,
                reason=reason,
                first_failure="volatility_explosion",
                gates=gates,
                entry_type=entry_type,
                regime_name=regime_key,
                gate_score=0,
                gate_max=_GATE_MAX_SCORE,
            )

        # ── Evaluate all 5 gates, collect scores ─────────────────────
        g1 = self._gate_score(enhanced_score, regime_key, gate_score_reduction)
        gates["gate1_score"] = g1

        g2 = self._gate_volume(df, entry_type)
        gates["gate2_volume"] = g2

        g3 = self._gate_volatility(df, indicators, regime_key, entry_type)
        gates["gate3_volatility"] = g3

        g4 = self._gate_spread(df, broker_key)
        gates["gate4_spread"] = g4

        g5 = self._gate_regime(regime_key, entry_type, side)
        gates["gate5_regime"] = g5

        # ── Tally weighted score ──────────────────────────────────────
        total_score = 0
        failed_gates = []
        for key, check in gates.items():
            w = _GATE_WEIGHTS.get(key, 0)
            if check.passed:
                total_score += w
            else:
                failed_gates.append(key)
                with self._lock:
                    self._gate_failures[key] = self._gate_failures.get(key, 0) + 1

        # Drought relaxation lowers the effective threshold.
        # Cap reduction at 50% and enforce a minimum of 2 points so that
        # at least two gate conditions must still be satisfied.
        capped_reduction = min(gate_score_reduction, 0.50)
        effective_threshold = max(
            2,
            int(BASE_ENTRY_SCORE_THRESHOLD * (1.0 - capped_reduction)),
        )
        passed = total_score >= effective_threshold

        if passed:
            with self._lock:
                self._total_passed += 1
            reason = (
                f"✅ Gate score {total_score}/{_GATE_MAX_SCORE} "
                f"≥ {effective_threshold} threshold | "
                f"{side.upper()} {entry_type} | regime={regime_key.upper()}"
            )
            first_failure = ""
        else:
            first_failure = failed_gates[0] if failed_gates else ""
            reason = (
                f"❌ Gate score {total_score}/{_GATE_MAX_SCORE} "
                f"< {effective_threshold} threshold | "
                f"failed: {', '.join(failed_gates)}"
            )

        logger.debug("AIEntryGate: %s", reason)
        return GateResult(
            passed=passed,
            reason=reason,
            first_failure=first_failure,
            gates=gates,
            entry_type=entry_type,
            regime_name=regime_key,
            gate_score=total_score,
            gate_max=_GATE_MAX_SCORE,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate pass/fail statistics."""
        with self._lock:
            return {
                "total_checked": self._total_checked,
                "total_passed":  self._total_passed,
                "pass_rate":     (
                    self._total_passed / self._total_checked
                    if self._total_checked > 0 else 0.0
                ),
                "gate_failures": dict(self._gate_failures),
            }

    # ------------------------------------------------------------------
    # Individual gate implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _gate_score(
        enhanced_score: float,
        regime_key: str,
        gate_score_reduction: float = 0.0,
    ) -> GateCheck:
        """Gate 1: AI predictive score vs regime-adjusted threshold."""
        threshold = _SCORE_THRESHOLDS.get(regime_key, _DEFAULT_SCORE_THRESHOLD)
        # Apply drought relaxation — lower threshold by the given fraction
        threshold = threshold * (1.0 - gate_score_reduction)
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
    def _gate_volume(df: pd.DataFrame, entry_type: str) -> GateCheck:
        """Gate 2: Current bar volume vs 20-bar average liquidity floor."""
        try:
            avg_vol = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else df["volume"].mean()
            cur_vol = float(df["volume"].iloc[-1])
            ratio   = cur_vol / avg_vol if avg_vol > 0 else 0.0
        except Exception:
            # Can't measure volume → pass with warning (don't block on data issue)
            return GateCheck(passed=True, name="Volume",
                             detail="volume data unavailable — gate skipped")

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
    ) -> GateCheck:
        """Gate 3: ATR% must be within [min, max] for the entry type."""
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

        passed = min_atr <= atr_pct <= max_atr
        reason = ""
        if atr_pct < min_atr:
            reason = f"ATR {atr_pct:.2f}% < {min_atr:.2f}% min (market too quiet)"
        elif atr_pct > max_atr:
            reason = f"ATR {atr_pct:.2f}% > {max_atr:.2f}% max (market too wild)"
        else:
            reason = f"ATR {atr_pct:.2f}% in [{min_atr:.2f}%, {max_atr:.2f}%]"

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
        """Gate 5: Regime must permit the requested entry type."""
        allowed = _REGIME_ALLOWED_ENTRIES.get(regime_key, _REGIME_ALLOWED_DEFAULT)
        passed = entry_type in allowed
        return GateCheck(
            passed=passed,
            name="Regime",
            detail=(
                f"regime={regime_key.upper()} "
                f"{'permits' if passed else 'discourages'} "
                f"{entry_type} {side} entry "
                f"(allowed types: {sorted(allowed)})"
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
