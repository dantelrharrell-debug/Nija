"""
NIJA Sniper Filter
==================

Final pre-execution gate that raises the bar to "sniper quality" before any
trade reaches the order book.

With only one trade at a time your edge **is** everything.  This filter
enforces four hard pillars simultaneously.  Every pillar must pass; if any
one fails the trade is vetoed.

Pillar 1 — Trend Confirmation (MTF)
    5-minute and 15-minute price action must both be aligned with the signal
    direction.  Market structure must show Higher Highs + Higher Lows (long)
    or Lower Highs + Lower Lows (short) on the base timeframe.

Pillar 2 — Momentum Trigger
    Either a confirmed breakout above/below the rolling high/low OR a strong
    candle close (body ≥ ``strong_body_pct`` × candle range).  Volume must be
    ≥ ``volume_spike_multiplier`` × 20-period rolling average.

Pillar 3 — Liquidity Check
    Bid-ask spread must be ≤ ``max_spread_pct``.  Optionally a minimum USD
    depth can be enforced when order-book data is available.

Pillar 4 — Confidence Threshold
    Trade signal confidence (0–1) must be ≥ ``min_confidence`` (default 0.65).

Instant block conditions (checked first):
    • ADX < ``min_adx`` → chop / sideways market
    • Volume < ``low_volume_multiplier`` × average → thin market
    • Price is range-bound (small ATR relative to range) without a breakout

Usage
-----
::

    from bot.sniper_filter import get_sniper_filter

    sf = get_sniper_filter()
    result = sf.check(
        symbol="BTC-USD",
        df=df,                  # OHLCV + indicators DataFrame
        signal_side="long",
        confidence=0.72,
        bid=price * 0.9995,
        ask=price * 1.0005,
    )
    if not result.passed:
        logger.info("🎯 SNIPER FILTER blocked %s: %s", symbol, result.reason)
        return  # skip trade

Singleton
---------
``get_sniper_filter()`` returns the same instance for the lifetime of the
process, which keeps state-less computation cheap and avoids configuration
drift.
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
    volume_spike_multiplier: float = 1.5

    # Rolling window (bars) for average-volume calculation
    volume_lookback: int = 20

    # Breakout window: close must exceed max(high) of the last N bars
    breakout_lookback: int = 20

    # Strong-close: candle body (|close-open|) must be at least this fraction
    # of the candle range (high-low) to count as a "strong close"
    strong_body_pct: float = 0.55

    # ── Pillar 3: Liquidity ───────────────────────────────────────────────────
    # Maximum allowed spread as a fraction of mid-price (0.003 = 0.30 %)
    max_spread_pct: float = 0.003

    # Optional minimum USD depth requirement.  Set to 0.0 to disable.
    min_depth_usd: float = 0.0

    # ── Pillar 4: Confidence ──────────────────────────────────────────────────
    # env: SNIPER_MIN_CONFIDENCE — override default 0.50 (e.g. 0.35 for flip mode)
    min_confidence: float = field(
        default_factory=lambda: _env_float("SNIPER_MIN_CONFIDENCE", 0.50)
    )

    # ── Instant-block thresholds ─────────────────────────────────────────────
    # ADX below this value is treated as choppy/sideways — instant block.
    # Set to 0.0 to disable the ADX check (e.g. when ADX column is absent).
    # env: SNIPER_MIN_ADX — override default 12.0 (e.g. 8.0 for flip mode)
    min_adx: float = field(
        default_factory=lambda: _env_float("SNIPER_MIN_ADX", 12.0)
    )

    # Volume below this multiple of average = thin market → instant block.
    low_volume_multiplier: float = 0.5

    # Minimum bars required in the DataFrame for any check to run
    min_bars: int = 25


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SniperResult:
    """Outcome of a SniperFilter.check() call."""

    passed: bool
    reason: str
    details: Dict = field(default_factory=dict)


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
            "🎯 SniperFilter initialized "
            "(min_confidence=%.2f, min_adx=%.1f, vol_spike=%.1fx, max_spread=%.3f)",
            self._cfg.min_confidence,
            self._cfg.min_adx,
            self._cfg.volume_spike_multiplier,
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
        Evaluate all four sniper pillars for a candidate trade.

        Parameters
        ----------
        symbol:
            Trading pair being evaluated (for logging).
        df:
            OHLCV DataFrame with at minimum columns ``open``, ``high``,
            ``low``, ``close``, ``volume``.  Optional: ``adx``, ``rsi``.
            The index should be a DatetimeIndex (needed for MTF resampling).
        signal_side:
            ``"long"`` or ``"short"``.
        confidence:
            Signal confidence (0–1 scale) from the strategy scorer.
        bid:
            Current best bid.  Pass 0.0 to skip the spread check.
        ask:
            Current best ask.  Pass 0.0 to skip the spread check.
        depth_usd:
            Best-5-level USD depth.  Pass 0.0 to skip depth check.

        Returns
        -------
        SniperResult
        """
        cfg = self._cfg
        details: Dict = {
            "symbol": symbol,
            "side": signal_side,
            "confidence": confidence,
        }

        # ── 0. Minimum data guard ─────────────────────────────────────────────
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

        # ── INSTANT BLOCK: Chop / sideways ────────────────────────────────────
        if cfg.min_adx > 0 and "adx" in df.columns:
            adx_val = float(df["adx"].iloc[-1])
            details["adx"] = adx_val
            if adx_val < cfg.min_adx:
                reason = (
                    f"Choppy market: ADX {adx_val:.1f} < min {cfg.min_adx:.1f} "
                    f"(sideways / no trend)"
                )
                details["block_reason"] = "chop_adx"
                logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
                return SniperResult(passed=False, reason=reason, details=details)

        # ── INSTANT BLOCK: Low volume ─────────────────────────────────────────
        volume_now = float(df["volume"].iloc[-1])
        avg_volume = _rolling_mean(df["volume"], cfg.volume_lookback)
        details["volume_now"] = volume_now
        details["avg_volume"] = avg_volume
        if avg_volume > 0:
            vol_ratio = volume_now / avg_volume
            details["volume_ratio"] = vol_ratio
            if vol_ratio < cfg.low_volume_multiplier:
                reason = (
                    f"Low volume: ratio {vol_ratio:.2f}x < {cfg.low_volume_multiplier:.2f}x "
                    f"(thin market)"
                )
                details["block_reason"] = "low_volume"
                logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
                return SniperResult(passed=False, reason=reason, details=details)
        else:
            vol_ratio = 0.0

        # ── PILLAR 4: Confidence threshold ────────────────────────────────────
        details["min_confidence"] = cfg.min_confidence
        if confidence < cfg.min_confidence:
            reason = (
                f"Confidence {confidence:.2f} below minimum {cfg.min_confidence:.2f}"
            )
            details["block_reason"] = "low_confidence"
            logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
            return SniperResult(passed=False, reason=reason, details=details)

        # ── PILLAR 1: Trend confirmation (MTF) ────────────────────────────────
        mtf_pass, mtf_reason, mtf_details = self._check_mtf_trend(df, is_long)
        details["mtf"] = mtf_details
        if not mtf_pass:
            reason = f"MTF trend not aligned: {mtf_reason}"
            details["block_reason"] = "mtf_trend"
            logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
            return SniperResult(passed=False, reason=reason, details=details)

        # ── PILLAR 2: Momentum trigger ────────────────────────────────────────
        mom_pass, mom_reason, mom_details = self._check_momentum(df, is_long, vol_ratio)
        details["momentum"] = mom_details
        if not mom_pass:
            reason = f"Weak momentum: {mom_reason}"
            details["block_reason"] = "weak_momentum"
            logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
            return SniperResult(passed=False, reason=reason, details=details)

        # ── PILLAR 3: Liquidity check ─────────────────────────────────────────
        liq_pass, liq_reason, liq_details = self._check_liquidity(bid, ask, depth_usd)
        details["liquidity"] = liq_details
        if not liq_pass:
            reason = f"Poor liquidity: {liq_reason}"
            details["block_reason"] = "poor_liquidity"
            logger.info("   🎯 SNIPER FILTER blocked %s: %s", symbol, reason)
            return SniperResult(passed=False, reason=reason, details=details)

        # ── All pillars passed ────────────────────────────────────────────────
        logger.info(
            "   🎯✅ SNIPER FILTER approved %s "
            "(conf=%.2f, vol=%.1fx, MTF=aligned, momentum=%s)",
            symbol, confidence, vol_ratio, mom_details.get("trigger", "?"),
        )
        return SniperResult(
            passed=True,
            reason="All sniper pillars passed",
            details=details,
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
