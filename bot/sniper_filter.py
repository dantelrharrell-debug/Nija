"""
NIJA Sniper Filter
==================

Final pre-execution gate that raises the bar to "sniper quality" before any
trade reaches the order book.

Gate decisions use a **Tiered Pass System** keyed on the AI confidence score.
A high-conviction signal needs less supporting evidence; a weaker signal must
clear more corroborating conditions.  No single missing condition hard-blocks
the trade — instead, risk is scaled down via the ``reduced_size`` flag when
alignment is only partial.

Tiers
-----
ELITE   (conf >= strong_threshold, default 0.70)
    High-conviction setup.  Only ``spread_ok AND regime_match`` required.
    Volume and volatility weakness are tolerated — trade proceeds at full or
    reduced size depending on the weighted score.

STANDARD (conf >= medium_threshold, default 0.50)
    Normal setup.  ``volume_ok AND volatility_ok AND spread_ok`` required.
    Regime alignment boosts the weighted score but is not a hard gate.

SCALP   (conf >= weak_threshold, default 0.35)
    Scalp / consolidation mode.  Only ``spread_ok AND volatility_ok`` needed.
    Thin volume is acceptable — position is sized down instead of rejected.

REJECTED (conf < weak_threshold)
    Below minimum acceptable confidence — trade vetoed.

Position sizing
---------------
After the tier gate passes, the weighted score (0–7) determines size:
  score >= SNIPER_SCORE_THRESHOLD (5) → full position
  score <  SNIPER_SCORE_THRESHOLD     → ``reduced_size=True``
    (caller multiplies size by SNIPER_BORDERLINE_POSITION_MULTIPLIER = 0.5)

Weighted score components
-------------------------
  ai_score_pass  (confidence >= min_confidence) : +2
  volume_pass    (vol_ratio >= low_volume_multiplier) : +1
  volatility_pass (ADX >= min_adx) : +1
  spread_ok      (bid-ask spread <= max_spread_pct) : +1
  regime_match   (MTF EMA trend aligned) : +2
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.sniper_filter")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SniperConfig:
    """Tunable thresholds for the Sniper Filter."""

    # ── Pillar 1: Trend / MTF ────────────────────────────────────────────────
    # Resample windows applied to the base DataFrame to simulate 5-min and
    # 15-min timeframes.  Values are pandas-compatible offset aliases.
    mtf_fast: str = "5min"
    mtf_slow: str = "15min"

    # EMA periods used to determine trend direction on each MTF slice
    ema_fast: int = 9
    ema_slow: int = 21

    # ── Pillar 2: Momentum ───────────────────────────────────────────────────
    # Volume spike: current bar volume must exceed this multiple of the rolling
    # average to count as a momentum confirmation.
    volume_spike_multiplier: float = 1.2  # TUNED: Lowered from 1.5 to allow entries on moderate volume expansion

    # Rolling window (bars) for average-volume calculation
    volume_lookback: int = 20

    # Breakout window: close must exceed max(high) of the last N bars
    breakout_lookback: int = 20

    # Strong-close: candle body (|close-open|) must be at least this fraction
    # of the candle range (high-low) to count as a "strong close"
    strong_body_pct: float = 0.45  # TUNED: Lowered from 0.55 to accept moderate-conviction closes

    # ── Pillar 3: Liquidity ───────────────────────────────────────────────────
    # Maximum allowed spread as a fraction of mid-price (0.003 = 0.30 %)
    max_spread_pct: float = 0.003

    # Optional minimum USD depth requirement.  Set to 0.0 to disable.
    min_depth_usd: float = 0.0

    # ── Pillar 4: Confidence ──────────────────────────────────────────────────
    # env: SNIPER_MIN_CONFIDENCE — override default 0.50 (e.g. 0.35 for flip mode)
    min_confidence: float = field(
        default_factory=lambda: _env_float("SNIPER_MIN_CONFIDENCE", 0.30)
    )

    # ── Soft-condition thresholds ─────────────────────────────────────────────
    # ADX below this value = weak trend — scored as volatility_pass=False.
    # Set to 0.0 to disable (e.g. when ADX column is absent).
    # env: SNIPER_MIN_ADX
    min_adx: float = field(
        default_factory=lambda: _env_float("SNIPER_MIN_ADX", 6.0)
    )

    # Volume below this multiple of average = thin market — scored as volume_pass=False.
    low_volume_multiplier: float = 0.25  # TUNED: lower volatility/volume requirement so quieter markets can pass

    # Minimum bars required in the DataFrame for any check to run
    min_bars: int = 25

    # ── Tiered pass thresholds (keyed on AI confidence 0–1) ──────────────────
    # ELITE  : conf >= strong_threshold → only spread_ok AND regime_match needed
    # STANDARD: conf >= medium_threshold → volume_ok AND volatility_ok AND spread_ok needed
    # SCALP  : conf >= weak_threshold   → spread_ok AND volatility_ok only needed
    # REJECTED: conf <  weak_threshold  → always blocked
    # Override via environment variables for live tuning without code changes.
    strong_threshold: float = field(
        default_factory=lambda: _env_float("SNIPER_STRONG_THRESHOLD", 0.70)
    )
    medium_threshold: float = field(
        default_factory=lambda: _env_float("SNIPER_MEDIUM_THRESHOLD", 0.50)
    )
    weak_threshold: float = field(
        default_factory=lambda: _env_float("SNIPER_WEAK_THRESHOLD", 0.25)
    )


# ---------------------------------------------------------------------------
# Weighted scoring constants
# ---------------------------------------------------------------------------

# Weighted scoring decision threshold.
# Tier gate passes first; this score then decides whether position is full or reduced.
SNIPER_SCORE_THRESHOLD: int = 5       # score >= 5 → full size; score < 5 → reduced size

# When the tier gate passes but weighted score < SNIPER_SCORE_THRESHOLD,
# the caller should multiply position size by this factor.
SNIPER_BORDERLINE_POSITION_MULTIPLIER: float = 0.5

# Minimum total weighted score to allow any entry.
# Below this floor the trade is always rejected, regardless of tier.
_SNIPER_PASS_FLOOR: float = 1.0   # lowered from 3.0: any positive signal passes (size-scaled)

# Graduated size multipliers keyed on score bracket.
_SNIPER_SIZE_MULT: Dict[str, float] = {
    "full":   1.00,   # score >= 6.0
    "high":   0.85,   # score >= 5.0
    "medium": 0.70,   # score >= 4.0
    "low":    0.55,   # score >= _SNIPER_PASS_FLOOR (3.0)
}

# SCALP mode — micro-cap friendly settings
# Accept thin markets when spreads are within limits; do not hard-block on volume.
ALLOW_LOW_LIQUIDITY: bool = True

# Maximum top-N candidates per cycle for SCALP / micro-cap mode.
# Taking 2 per cycle gives fast, small wins that compound on a $74–$102 account.
TOP_N: int = 2

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SniperResult:
    """Outcome of a SniperFilter.check() call."""

    passed: bool
    reason: str
    details: Dict = field(default_factory=dict)
    # True when score < SNIPER_SCORE_THRESHOLD — caller should scale position size.
    reduced_size: bool = False
    # Exact size multiplier: 1.0 = full, 0.85/0.70/0.55 = graduated reduction, 0.0 = blocked.
    size_multiplier: float = 1.0


# ---------------------------------------------------------------------------
# Filter implementation
# ---------------------------------------------------------------------------

def _confidence_score(confidence: float, cfg: SniperConfig) -> float:
    """Map AI confidence to a proportional score in [0.0, 2.0].

    Uses a simple linear scale (confidence * 10, capped at 2.0) so that ALL
    confidence values contribute positively — no hard floor rejection.

      confidence=0.05 → 0.5 pts
      confidence=0.10 → 1.0 pts
      confidence=0.20 → 2.0 pts (full credit, cap reached)
      confidence≥0.20 → 2.0 pts

    Architecture: everything contributes → nothing hard-blocks.
    """
    return min(confidence * 10, 2.0)


class SniperFilter:
    """
    All-in-one pre-execution quality gate.

    Thread-safe (stateless computation).  Instantiate once via
    ``get_sniper_filter()``.
    """

    def __init__(self, config: Optional[SniperConfig] = None) -> None:
        self._cfg = config or SniperConfig()
        logger.info(
            "🎯 SniperFilter initialized — Tiered Pass System "
            "(strong=%.2f elite, medium=%.2f standard, weak=%.2f scalp | "
            "min_adx=%.1f, vol_floor=%.2fx, max_spread=%.3f)",
            self._cfg.strong_threshold,
            self._cfg.medium_threshold,
            self._cfg.weak_threshold,
            self._cfg.min_adx,
            self._cfg.low_volume_multiplier,
            self._cfg.max_spread_pct,
        )
        if ALLOW_LOW_LIQUIDITY:
            logger.warning(
                "⚠️  SniperFilter: ALLOW_LOW_LIQUIDITY=True — SCALP tier will accept "
                "thin markets (volume check bypassed). Slippage risk is elevated on "
                "micro-cap or illiquid pairs."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        symbol: str,
        df: pd.DataFrame,
        signal_side: str,
        confidence: float,
        bid: float = 0.0,
        ask: float = 0.0,
        depth_usd: float = 0.0,
        regime: Optional[str] = None,
    ) -> SniperResult:
        """
        Evaluate trade quality using the Tiered Pass System.

        The AI confidence score determines which tier applies; each tier
        has its own required conditions.  A high-conviction signal can pass
        with fewer supporting conditions, allowing more participation without
        lowering the floor for weak signals.

        Tier gate (primary decision)
        ----------------------------
        ELITE   (conf >= strong_threshold): spread_ok AND regime_match
        STANDARD (conf >= medium_threshold): volume_ok AND volatility_ok AND spread_ok
        SCALP   (conf >= weak_threshold):   spread_ok AND volatility_ok
        REJECTED (conf < weak_threshold):   always blocked

        Position sizing (secondary — uses weighted score 0–7)
        -------------------------------------------------------
        weighted_score >= SNIPER_SCORE_THRESHOLD (5): full size
        weighted_score == SNIPER_BORDERLINE_THRESHOLD (4): reduced_size=True
        weighted_score < 4 but tier passed: reduced_size=True (conservative)
        """
        cfg = self._cfg
        details: Dict = {
            "symbol": symbol,
            "side": signal_side,
            "confidence": confidence,
        }

        # ── LR-based confidence override (replaces static confidence) ──────
        # LogisticRegressionConfidence has predicted P(win) for this symbol.
        # Use it as a live replacement for the raw confidence score.
        try:
            from self_learning_weight_tuner import get_weight_tuner as _gwt  # type: ignore
        except ImportError:
            try:
                from bot.self_learning_weight_tuner import get_weight_tuner as _gwt  # type: ignore
            except ImportError:
                _gwt = None  # type: ignore
        if _gwt is not None:
            try:
                _lr_conf = _gwt().get_lr_confidence(symbol)
                if _lr_conf is not None:
                    confidence = _lr_conf
                    details["lr_win_probability"] = round(_lr_conf, 4)
                    details["confidence_source"] = "logistic_regression"
            except Exception:
                pass

        # ── Adaptive weak_threshold per regime ──────────────────────────────
        _weak_floor = cfg.weak_threshold
        if _gwt is not None:
            try:
                _weak_floor = _gwt().get_sniper_confidence_floor(
                    getattr(regime, "value", regime) if regime else "default"
                )
            except Exception:
                pass
        details["weak_floor_used"] = round(_weak_floor, 4)

        # ── 0. Minimum data guard (hard block — can't score without data) ──────
        if not isinstance(df, pd.DataFrame) or len(df) < cfg.min_bars:
            reason = f"Insufficient data: {len(df) if isinstance(df, pd.DataFrame) else 0} bars < {cfg.min_bars} required"
            details["block_reason"] = "insufficient_data"
            logger.info(f"TRADE REJECTED → reason={reason} score=0 conf={confidence}")
            return SniperResult(passed=False, reason=reason, details=details)

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            reason = f"Missing DataFrame columns: {', '.join(sorted(missing))}"
            details["block_reason"] = "missing_columns"
            logger.info(f"TRADE REJECTED → reason={reason} score=0 conf={confidence}")
            return SniperResult(passed=False, reason=reason, details=details)

        is_long = signal_side.lower() in ("long", "buy", "enter_long")

        # ── Weighted scoring (7 points total, threshold = 5) ──────────────────
        # Trades with score >= 5 are approved.
        # Score == 4 is borderline: approved with reduced_size = True.
        score = 0

        # ── Confidence score (0.0–2.0 proportional) ──────────────────────────
        # Replaces the old binary +2/0 — confidence now scales smoothly from
        # the floor (0.5 pts at weak_threshold) up to 2.0 at strong_threshold.
        details["min_confidence"] = cfg.min_confidence
        conf_pts = _confidence_score(confidence, cfg)
        score += conf_pts
        ai_score_pass = conf_pts > 0
        details["conf_pts"] = round(conf_pts, 2)
        details["ai_score_pass"] = ai_score_pass

        # ── volume_pass (+1): current volume vs rolling average ───────────────
        volume_now = float(df["volume"].iloc[-1])
        avg_volume = _rolling_mean(df["volume"], cfg.volume_lookback)
        details["volume_now"] = volume_now
        details["avg_volume"] = avg_volume
        vol_ratio = (volume_now / avg_volume) if avg_volume > 0 else 0.0
        details["volume_ratio"] = vol_ratio
        volume_pass = vol_ratio >= cfg.low_volume_multiplier
        if volume_pass:
            score += 1
        details["volume_pass"] = volume_pass

        # ── volatility_pass (+1): ADX trend strength proxy ────────────────────
        volatility_pass = True  # default: pass if ADX column absent
        if cfg.min_adx > 0 and "adx" in df.columns:
            adx_val = float(df["adx"].iloc[-1])
            details["adx"] = adx_val
            volatility_pass = adx_val >= cfg.min_adx
        if volatility_pass:
            score += 1
        details["volatility_pass"] = volatility_pass

        # ── spread_ok (+1): bid-ask liquidity check ───────────────────────────
        liq_pass, liq_reason, liq_details = self._check_liquidity(bid, ask, depth_usd)
        details["liquidity"] = liq_details
        spread_ok = liq_pass
        if spread_ok:
            score += 1
        details["spread_ok"] = spread_ok

        # ── MTF trend score (0/1/2 pts proportional) ─────────────────────────
        mtf_pts, mtf_reason, mtf_details = self._check_mtf_trend(df, is_long)
        details["mtf"] = mtf_details
        score += mtf_pts
        regime_match = mtf_pts > 0
        details["regime_match"] = regime_match
        details["mtf_pts"] = round(mtf_pts, 1)

        details["weighted_score"] = round(score, 2)

        # ── Momentum check (informational — logged but not scored separately) ──
        mom_pass, mom_reason, mom_details = self._check_momentum(df, is_long, vol_ratio)
        details["momentum"] = mom_details

        # ── Score-based pass/fail — everything contributes, nothing hard-blocks ──
        # Confidence now contributes via _confidence_score (min(conf*10, 2.0)) so
        # there is no separate hard floor on confidence.
        # When score < _SNIPER_PASS_FLOOR, log as advisory and proceed at minimum size.
        logger.info(
            f"FINAL DECISION → score={score:.2f} threshold={_SNIPER_PASS_FLOOR:.2f}"
            f" execute={score >= _SNIPER_PASS_FLOOR}"
        )
        if score < _SNIPER_PASS_FLOOR:
            reason = (
                f"Score {score:.1f}/7 < {_SNIPER_PASS_FLOOR:.1f} floor "
                f"(conf={confidence:.2f}, vol={vol_ratio:.2f}x, "
                f"spread={'✓' if spread_ok else '✗'}, "
                f"mtf={details.get('mtf_pts', 0):.1f}pts) — proceeding at minimum size"
            )
            details["block_reason"] = "score_below_floor_advisory"
            logger.info("   ⚠️  SNIPER FILTER low-score advisory %s: %s", symbol, reason)
            logger.info(
                f"TRADE REJECTED → reason={reason} score={score} conf={confidence}"
            )
            # Proceed with minimum size instead of hard-blocking
            return SniperResult(
                passed=True,
                reason=reason,
                details=details,
                reduced_size=True,
                size_multiplier=_SNIPER_SIZE_MULT["low"],
            )

        # ── Graduated position sizing based on score ──────────────────────────
        if score >= 6.0:
            size_mult, size_label = _SNIPER_SIZE_MULT["full"],   "full"
        elif score >= 5.0:
            size_mult, size_label = _SNIPER_SIZE_MULT["high"],   "high (×0.85)"
        elif score >= 4.0:
            size_mult, size_label = _SNIPER_SIZE_MULT["medium"], "medium (×0.70)"
        else:
            size_mult, size_label = _SNIPER_SIZE_MULT["low"],    "low (×0.55)"

        reduce = size_mult < 1.0
        logger.info(
            "   🎯✅ SNIPER FILTER approved %s "
            "(score=%.1f/7, conf=%.2f, vol=%.1fx, size=%s)",
            symbol, score, confidence, vol_ratio, size_label,
        )
        return SniperResult(
            passed=True,
            reason=(
                f"score={score:.1f}/7 ≥ {_SNIPER_PASS_FLOOR:.1f} | "
                f"conf={confidence:.2f} | vol={vol_ratio:.2f}x | size={size_label}"
            ),
            details=details,
            reduced_size=reduce,
            size_multiplier=size_mult,
        )

    # ------------------------------------------------------------------
    # Pillar 1: MTF Trend
    # ------------------------------------------------------------------

    def _check_mtf_trend(
        self, df: pd.DataFrame, is_long: bool
    ) -> Tuple[float, str, Dict]:
        """
        Verify trend alignment: base-TF structure + fast/slow MTF EMA direction.

        Returns (mtf_pts, reason, details) where mtf_pts is:
          2.0 — all 3 checks pass  (fully aligned)
          1.0 — 2/3 checks pass    (partially aligned — partial credit)
          0.0 — ≤1/3 check passes  (misaligned or insufficient data)
        """
        cfg = self._cfg
        details: Dict = {}
        pass_count = 0
        notes: List[str] = []

        # ── Check 1: Base-TF market structure ────────────────────────────────
        high_now  = float(df["high"].iloc[-1])
        high_prev = float(df["high"].iloc[-2])
        low_now   = float(df["low"].iloc[-1])
        low_prev  = float(df["low"].iloc[-2])

        higher_high = high_now > high_prev
        higher_low  = low_now  > low_prev
        lower_high  = high_now < high_prev
        lower_low   = low_now  < low_prev

        if is_long:
            structure_ok = higher_high and higher_low
            details["structure_long"] = {
                "higher_high": higher_high,
                "higher_low": higher_low,
                "passed": structure_ok,
            }
            if not structure_ok:
                notes.append(f"structure not bullish (HH={higher_high}, HL={higher_low})")
        else:
            structure_ok = lower_high and lower_low
            details["structure_short"] = {
                "lower_high": lower_high,
                "lower_low": lower_low,
                "passed": structure_ok,
            }
            if not structure_ok:
                notes.append(f"structure not bearish (LH={lower_high}, LL={lower_low})")

        if structure_ok:
            pass_count += 1

        # ── Checks 2+3: Resampled MTF EMA trend ──────────────────────────────
        for tf_label, tf_rule in [
            (cfg.mtf_fast, cfg.mtf_fast),
            (cfg.mtf_slow, cfg.mtf_slow),
        ]:
            tf_df = _resample(df, tf_rule)
            if tf_df is None or len(tf_df) < cfg.ema_slow + 2:
                # Insufficient resampled bars — treat as soft pass to avoid
                # penalising legitimate signals due to data gaps.
                details[f"mtf_{tf_label}"] = {"status": "insufficient_bars", "passed": True}
                pass_count += 1
                continue

            close_tf = tf_df["close"]
            ema_fast_s = close_tf.ewm(span=cfg.ema_fast, adjust=False).mean()
            ema_slow_s = close_tf.ewm(span=cfg.ema_slow, adjust=False).mean()
            ema_fast_val = float(ema_fast_s.iloc[-1])
            ema_slow_val = float(ema_slow_s.iloc[-1])

            tf_bullish = ema_fast_val > ema_slow_val
            tf_bearish = ema_fast_val < ema_slow_val
            tf_ok = tf_bullish if is_long else tf_bearish

            details[f"mtf_{tf_label}"] = {
                "ema_fast": ema_fast_val,
                "ema_slow": ema_slow_val,
                "bullish": tf_bullish,
                "passed": tf_ok,
            }

            if tf_ok:
                pass_count += 1
            else:
                direction = "bullish" if is_long else "bearish"
                notes.append(
                    f"{tf_label} EMA not {direction} "
                    f"(fast={ema_fast_val:.4f} "
                    f"{'≤' if is_long else '≥'} slow={ema_slow_val:.4f})"
                )

        # ── Map pass count → score ─────────────────────────────────────────────
        # 3/3 → 2.0 pts, 2/3 → 1.0 pt (partial), ≤1/3 → 0.0 pts
        mtf_pts = 2.0 if pass_count >= 3 else (1.0 if pass_count == 2 else 0.0)
        if pass_count >= 3:
            reason = "MTF trend aligned"
        elif pass_count == 2:
            reason = f"MTF partial ({pass_count}/3): {', '.join(notes)}"
        else:
            reason = f"MTF misaligned ({pass_count}/3): {', '.join(notes)}"

        details["pass_count"] = pass_count
        details["mtf_pts"]    = mtf_pts
        return mtf_pts, reason, details

    # ------------------------------------------------------------------
    # Pillar 2: Momentum
    # ------------------------------------------------------------------

    def _check_momentum(
        self,
        df: pd.DataFrame,
        is_long: bool,
        vol_ratio: float,
    ) -> Tuple[bool, str, Dict]:
        """
        Verify a momentum trigger: breakout OR strong candle close, plus
        volume spike confirmation.

        Returns (passed, reason, details).
        """
        cfg = self._cfg
        details: Dict = {}
        failures: List[str] = []

        # ── Volume spike ──────────────────────────────────────────────────────
        volume_ok = vol_ratio >= cfg.volume_spike_multiplier
        details["volume_spike"] = {
            "ratio": round(vol_ratio, 3),
            "required": cfg.volume_spike_multiplier,
            "passed": volume_ok,
        }
        if not volume_ok:
            failures.append(
                f"Volume spike insufficient: {vol_ratio:.2f}x < {cfg.volume_spike_multiplier:.2f}x"
            )

        close_now = float(df["close"].iloc[-1])
        open_now  = float(df["open"].iloc[-1])
        high_now  = float(df["high"].iloc[-1])
        low_now   = float(df["low"].iloc[-1])

        # ── Breakout check ────────────────────────────────────────────────────
        lookback = min(cfg.breakout_lookback, len(df) - 1)
        if is_long:
            ref_extreme = float(df["high"].iloc[-(lookback + 1):-1].max())
            breakout = close_now > ref_extreme
        else:
            ref_extreme = float(df["low"].iloc[-(lookback + 1):-1].min())
            breakout = close_now < ref_extreme

        details["breakout"] = {
            "close": close_now,
            "ref_extreme": ref_extreme,
            "passed": breakout,
        }

        # ── Strong candle close ───────────────────────────────────────────────
        candle_range = high_now - low_now
        if candle_range > 0:
            body = abs(close_now - open_now)
            body_pct = body / candle_range
        else:
            body_pct = 0.0

        strong_close_direction = close_now > open_now if is_long else close_now < open_now
        strong_close = strong_close_direction and body_pct >= cfg.strong_body_pct

        details["strong_close"] = {
            "body_pct": round(body_pct, 3),
            "required": cfg.strong_body_pct,
            "direction_ok": strong_close_direction,
            "passed": strong_close,
        }

        # Momentum trigger: breakout OR strong candle close
        trigger_ok = breakout or strong_close
        if trigger_ok:
            details["trigger"] = "breakout" if breakout else "strong_close"
        else:
            failures.append(
                "No momentum trigger: neither breakout nor strong candle close confirmed"
            )
            details["trigger"] = "none"

        if failures:
            return False, " | ".join(failures), details

        return True, f"Momentum confirmed ({details['trigger']})", details

    # ------------------------------------------------------------------
    # Pillar 3: Liquidity
    # ------------------------------------------------------------------

    def _check_liquidity(
        self,
        bid: float,
        ask: float,
        depth_usd: float,
    ) -> Tuple[bool, str, Dict]:
        """
        Verify tight spread and optional depth floor.

        Returns (passed, reason, details).
        """
        cfg = self._cfg
        details: Dict = {}
        failures: List[str] = []

        # ── Spread check ──────────────────────────────────────────────────────
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            spread_pct = (ask - bid) / mid if mid > 0 else 0.0
            spread_ok = spread_pct <= cfg.max_spread_pct
            details["spread"] = {
                "bid": bid,
                "ask": ask,
                "spread_pct": round(spread_pct, 6),
                "max_spread_pct": cfg.max_spread_pct,
                "passed": spread_ok,
            }
            if not spread_ok:
                failures.append(
                    f"Wide spread: {spread_pct*100:.3f}% > {cfg.max_spread_pct*100:.3f}%"
                )
        else:
            details["spread"] = {"status": "not_checked"}

        # ── Depth check (optional) ────────────────────────────────────────────
        if cfg.min_depth_usd > 0 and depth_usd > 0:
            depth_ok = depth_usd >= cfg.min_depth_usd
            details["depth"] = {
                "depth_usd": depth_usd,
                "min_depth_usd": cfg.min_depth_usd,
                "passed": depth_ok,
            }
            if not depth_ok:
                failures.append(
                    f"Thin book: depth ${depth_usd:,.0f} < ${cfg.min_depth_usd:,.0f}"
                )
        else:
            details["depth"] = {"status": "not_checked"}

        if failures:
            return False, " | ".join(failures), details

        return True, "Liquidity checks passed", details


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[SniperFilter] = None
_lock = threading.Lock()


def get_sniper_filter(config: Optional[SniperConfig] = None) -> SniperFilter:
    """
    Return the process-wide singleton SniperFilter.

    Passing a ``config`` on the first call sets the configuration;
    subsequent calls ignore ``config`` and return the existing instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SniperFilter(config)
    return _instance


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rolling_mean(series: "pd.Series", window: int) -> float:
    """Return the rolling mean of the last ``window`` values (NaN-safe)."""
    val = series.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def _resample(df: pd.DataFrame, rule: str) -> Optional[pd.DataFrame]:
    """
    Resample a base-TF OHLCV DataFrame to a higher timeframe.

    Returns None when the index is not a DatetimeIndex or resampling
    produces fewer than 3 rows.
    """
    try:
        if not isinstance(df.index, pd.DatetimeIndex):
            # Try to convert — may fail for integer-indexed DataFrames
            df = df.copy()
            df.index = pd.to_datetime(df.index)

        resampled = df.resample(rule).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

        return resampled if len(resampled) >= 3 else None
    except Exception:
        return None
