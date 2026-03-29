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
        default_factory=lambda: _env_float("SNIPER_MIN_CONFIDENCE", 0.45)
    )

    # ── Soft-condition thresholds ─────────────────────────────────────────────
    # ADX below this value = weak trend — scored as volatility_pass=False.
    # Set to 0.0 to disable (e.g. when ADX column is absent).
    # env: SNIPER_MIN_ADX
    min_adx: float = field(
        default_factory=lambda: _env_float("SNIPER_MIN_ADX", 10.0)
    )

    # Volume below this multiple of average = thin market — scored as volume_pass=False.
    low_volume_multiplier: float = 0.4  # TUNED: allows quieter markets that were previously hard-blocked

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
        default_factory=lambda: _env_float("SNIPER_WEAK_THRESHOLD", 0.35)
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

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SniperResult:
    """Outcome of a SniperFilter.check() call."""

    passed: bool
    reason: str
    details: Dict = field(default_factory=dict)
    # True when the tier gate passed but the weighted score < SNIPER_SCORE_THRESHOLD.
    # The caller should multiply position size by SNIPER_BORDERLINE_POSITION_MULTIPLIER.
    reduced_size: bool = False


# ---------------------------------------------------------------------------
# Filter implementation
# ---------------------------------------------------------------------------

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

        # ── 0. Minimum data guard (hard block — can't score without data) ──────
        if not isinstance(df, pd.DataFrame) or len(df) < cfg.min_bars:
            reason = f"Insufficient data: {len(df) if isinstance(df, pd.DataFrame) else 0} bars < {cfg.min_bars} required"
            details["block_reason"] = "insufficient_data"
            return SniperResult(passed=False, reason=reason, details=details)

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            reason = f"Missing DataFrame columns: {', '.join(sorted(missing))}"
            details["block_reason"] = "missing_columns"
            return SniperResult(passed=False, reason=reason, details=details)

        is_long = signal_side.lower() in ("long", "buy", "enter_long")

        # ── Weighted scoring (7 points total, threshold = 5) ──────────────────
        # Trades with score >= 5 are approved.
        # Score == 4 is borderline: approved with reduced_size = True.
        score = 0

        # ── ai_score_pass (+2): confidence vs threshold ───────────────────────
        details["min_confidence"] = cfg.min_confidence
        ai_score_pass = confidence >= cfg.min_confidence
        if ai_score_pass:
            score += 2
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

        # ── regime_match (+2): MTF trend alignment ────────────────────────────
        mtf_pass, mtf_reason, mtf_details = self._check_mtf_trend(df, is_long)
        details["mtf"] = mtf_details
        regime_match = mtf_pass
        if regime_match:
            score += 2
        details["regime_match"] = regime_match

        details["weighted_score"] = score

        # ── Momentum check (informational — logged but not scored separately) ──
        mom_pass, mom_reason, mom_details = self._check_momentum(df, is_long, vol_ratio)
        details["momentum"] = mom_details

        # ── Tiered Pass System — primary gate decision ────────────────────────
        #
        # ELITE: high-conviction signal → only spread + regime needed.
        #   Volume and volatility are desirable but not blocking.
        #
        # STANDARD: normal signal → volume + volatility + spread all needed.
        #   Regime alignment is a bonus for position sizing, not a gate.
        #
        # SCALP: weaker signal in scalp/consolidation mode → spread + volatility.
        #   Volume can be thin; we trade smaller rather than reject entirely.
        #
        # REJECTED: confidence below the floor → no trade.

        if confidence >= cfg.strong_threshold:
            tier = "ELITE"
            tier_pass = spread_ok and regime_match
            tier_reason = (
                f"ELITE tier (conf={confidence:.2f} >= {cfg.strong_threshold:.2f}): "
                f"spread={'✓' if spread_ok else '✗'} regime={'✓' if regime_match else '✗'}"
            )
        elif confidence >= cfg.medium_threshold:
            tier = "STANDARD"
            tier_pass = volume_pass and volatility_pass and spread_ok
            tier_reason = (
                f"STANDARD tier (conf={confidence:.2f} >= {cfg.medium_threshold:.2f}): "
                f"volume={'✓' if volume_pass else '✗'} "
                f"volatility={'✓' if volatility_pass else '✗'} "
                f"spread={'✓' if spread_ok else '✗'}"
            )
        elif confidence >= cfg.weak_threshold:
            tier = "SCALP"
            tier_pass = spread_ok and volatility_pass
            tier_reason = (
                f"SCALP tier (conf={confidence:.2f} >= {cfg.weak_threshold:.2f}): "
                f"spread={'✓' if spread_ok else '✗'} "
                f"volatility={'✓' if volatility_pass else '✗'}"
            )
        else:
            tier = "REJECTED"
            tier_pass = False
            tier_reason = (
                f"REJECTED: confidence {confidence:.2f} < "
                f"weak_threshold {cfg.weak_threshold:.2f}"
            )

        details["tier"] = tier
        details["tier_pass"] = tier_pass
        details["tier_reason"] = tier_reason

        if not tier_pass:
            details["block_reason"] = f"tier_{tier.lower()}_failed"
            logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, tier_reason)
            return SniperResult(passed=False, reason=tier_reason, details=details)

        # ── Position sizing via weighted score ────────────────────────────────
        # Tier gate passed.  Use the weighted score to decide whether the
        # position should be full-size or reduced.
        reduce = score < SNIPER_SCORE_THRESHOLD  # score < 5 → borderline size
        size_note = (
            "full size"
            if not reduce
            else f"reduced size x{SNIPER_BORDERLINE_POSITION_MULTIPLIER}"
        )

        logger.info(
            "   🎯✅ SNIPER FILTER approved %s "
            "(tier=%s, score=%d/7, conf=%.2f, vol=%.1fx, %s)",
            symbol, tier, score, confidence, vol_ratio, size_note,
        )
        return SniperResult(
            passed=True,
            reason=f"{tier_reason} | weighted={score}/7 | {size_note}",
            details=details,
            reduced_size=reduce,
        )

    # ------------------------------------------------------------------
    # Pillar 1: MTF Trend
    # ------------------------------------------------------------------

    def _check_mtf_trend(
        self, df: pd.DataFrame, is_long: bool
    ) -> Tuple[bool, str, Dict]:
        """
        Verify trend alignment on fast (5-min) and slow (15-min) timeframes.

        Returns (passed, reason, details).
        """
        cfg = self._cfg
        details: Dict = {}
        failures: List[str] = []

        # ── Base-TF market structure: HH+HL (long) or LH+LL (short) ─────────
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
                failures.append(
                    f"Base-TF structure not bullish "
                    f"(HH={higher_high}, HL={higher_low})"
                )
        else:
            structure_ok = lower_high and lower_low
            details["structure_short"] = {
                "lower_high": lower_high,
                "lower_low": lower_low,
                "passed": structure_ok,
            }
            if not structure_ok:
                failures.append(
                    f"Base-TF structure not bearish "
                    f"(LH={lower_high}, LL={lower_low})"
                )

        # ── Resampled MTF EMA trend checks ───────────────────────────────────
        for tf_label, tf_rule in [
            (cfg.mtf_fast, cfg.mtf_fast),
            (cfg.mtf_slow, cfg.mtf_slow),
        ]:
            tf_df = _resample(df, tf_rule)
            if tf_df is None or len(tf_df) < cfg.ema_slow + 2:
                # Not enough resampled bars — treat as a soft pass (don't block)
                details[f"mtf_{tf_label}"] = {"status": "insufficient_bars", "passed": True}
                continue

            close_tf = tf_df["close"]
            ema_fast_s = close_tf.ewm(span=cfg.ema_fast, adjust=False).mean()
            ema_slow_s = close_tf.ewm(span=cfg.ema_slow, adjust=False).mean()
            ema_fast_val = float(ema_fast_s.iloc[-1])
            ema_slow_val = float(ema_slow_s.iloc[-1])

            tf_bullish = ema_fast_val > ema_slow_val
            tf_bearish = ema_fast_val < ema_slow_val

            if is_long and not tf_bullish:
                failures.append(
                    f"{tf_label} EMA not bullish "
                    f"(fast={ema_fast_val:.4f} ≤ slow={ema_slow_val:.4f})"
                )
            elif not is_long and not tf_bearish:
                failures.append(
                    f"{tf_label} EMA not bearish "
                    f"(fast={ema_fast_val:.4f} ≥ slow={ema_slow_val:.4f})"
                )

            details[f"mtf_{tf_label}"] = {
                "ema_fast": ema_fast_val,
                "ema_slow": ema_slow_val,
                "bullish": tf_bullish,
                "passed": tf_bullish if is_long else tf_bearish,
            }

        if failures:
            return False, " | ".join(failures), details

        return True, "MTF trend aligned", details

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
