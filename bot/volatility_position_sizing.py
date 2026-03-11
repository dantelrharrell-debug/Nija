"""
NIJA Volatility Position Sizing
=================================

Dynamically adjusts proposed position sizes based on current market
volatility so that every trade carries a similar level of risk regardless
of how choppy or calm the underlying asset is.

Core principle
--------------
  adjusted_size = proposed_size × (target_volatility / current_volatility)

A calm market (low ATR) receives a larger position; a volatile market
(high ATR) receives a smaller one.  The result is clamped between a
configurable minimum and maximum fraction of the account balance.

Features
--------
- ATR-based volatility measurement (14-period default)
- Volatility regime detection: EXTREME_LOW / LOW / NORMAL / HIGH / EXTREME_HIGH
- Per-regime safety multipliers (e.g. EXTREME_HIGH → 0.40×)
- Fallback to base position when insufficient price history is available
- Singleton convenience accessor ``get_volatility_position_sizer()``

Usage::

    from bot.volatility_position_sizing import get_volatility_position_sizer

    sizer = get_volatility_position_sizer()

    adjusted_size, details = sizer.adjust(
        df=ohlcv_df,
        current_price=current_price,
        proposed_size_usd=position_size,
        account_balance=account_balance,
    )

    position_size = adjusted_size  # use the volatility-aware size

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.volatility_position_sizing")


# ---------------------------------------------------------------------------
# Import VolatilityAdaptiveSizer (graceful fallback)
# ---------------------------------------------------------------------------
try:
    from volatility_adaptive_sizing import VolatilityAdaptiveSizer
    _ADAPTIVE_SIZER_AVAILABLE = True
except ImportError:
    try:
        from bot.volatility_adaptive_sizing import VolatilityAdaptiveSizer
        _ADAPTIVE_SIZER_AVAILABLE = True
    except ImportError:
        _ADAPTIVE_SIZER_AVAILABLE = False
        VolatilityAdaptiveSizer = None  # type: ignore
        logger.warning("⚠️  VolatilityAdaptiveSizer unavailable – using built-in fallback")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VolatilitySizingResult:
    """
    Result of a volatility-based position-size adjustment.

    Attributes:
        original_size_usd:  Proposed size before adjustment.
        adjusted_size_usd:  Volatility-adjusted size.
        size_multiplier:    Ratio adjusted/original (clamped to [0.25, 2.0]).
        volatility_regime:  Detected regime label.
        atr_pct:            Current ATR as % of price.
        method:             Sizing method used (``"adaptive"`` or ``"fallback"``).
        details:            Full breakdown dict for logging.
    """
    original_size_usd: float
    adjusted_size_usd: float
    size_multiplier: float
    volatility_regime: str
    atr_pct: float
    method: str
    details: Dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"VolSizing: ${self.original_size_usd:.2f} → ${self.adjusted_size_usd:.2f} "
            f"({self.size_multiplier:.2f}x) regime={self.volatility_regime} "
            f"atr={self.atr_pct:.2f}% method={self.method}"
        )


# ---------------------------------------------------------------------------
# Volatility position sizer
# ---------------------------------------------------------------------------

# Regime size caps used when VolatilityAdaptiveSizer is unavailable.
_REGIME_CAPS: Dict[str, float] = {
    "EXTREME_HIGH": 0.40,
    "HIGH":         0.65,
    "NORMAL":       1.00,
    "LOW":          1.10,
    "EXTREME_LOW":  1.25,
}

# ATR percentile thresholds for the built-in fallback regime detector.
_REGIME_THRESHOLDS: Dict[str, Tuple[float, float]] = {
    # regime: (min_atr_pct, max_atr_pct)
    "EXTREME_LOW":  (0.0,  0.5),
    "LOW":          (0.5,  1.0),
    "NORMAL":       (1.0,  3.0),
    "HIGH":         (3.0,  6.0),
    "EXTREME_HIGH": (6.0,  float("inf")),
}


class VolatilityPositionSizer:
    """
    Adjust position sizes based on current market volatility.

    Args:
        base_position_pct:    Base position size as fraction of balance
                              (default 0.05 = 5 %).
        target_volatility_pct: Target ATR % the sizer normalises against
                               (default 2.0 %).
        min_position_pct:     Minimum allowed position as fraction of balance
                               (default 0.01 = 1 %).
        max_position_pct:     Maximum allowed position as fraction of balance
                               (default 0.15 = 15 %).
        atr_period:           ATR look-back period in bars (default 14).
        volatility_lookback:  Historical bars used for regime detection
                               (default 50).
        enable_regime_cap:    Apply additional per-regime safety multipliers
                               on top of the inverse-volatility scaling
                               (default ``True``).
    """

    def __init__(
        self,
        base_position_pct: float = 0.05,
        target_volatility_pct: float = 2.0,
        min_position_pct: float = 0.01,
        max_position_pct: float = 0.15,
        atr_period: int = 14,
        volatility_lookback: int = 50,
        enable_regime_cap: bool = True,
    ):
        self.base_position_pct = base_position_pct
        self.target_volatility_pct = target_volatility_pct
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.atr_period = atr_period
        self.volatility_lookback = volatility_lookback
        self.enable_regime_cap = enable_regime_cap

        # Try to use the full adaptive sizer
        if _ADAPTIVE_SIZER_AVAILABLE and VolatilityAdaptiveSizer is not None:
            self._sizer = VolatilityAdaptiveSizer(
                base_position_pct=base_position_pct,
                target_volatility_pct=target_volatility_pct,
                min_position_pct=min_position_pct,
                max_position_pct=max_position_pct,
                atr_period=atr_period,
                volatility_lookback=volatility_lookback,
            )
        else:
            self._sizer = None

        logger.info(
            f"✅ VolatilityPositionSizer initialized "
            f"(target_vol={target_volatility_pct:.1f}% "
            f"range={min_position_pct*100:.0f}%-{max_position_pct*100:.0f}% "
            f"backend={'adaptive' if self._sizer else 'builtin'})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adjust(
        self,
        df: pd.DataFrame,
        current_price: float,
        proposed_size_usd: float,
        account_balance: float,
    ) -> Tuple[float, VolatilitySizingResult]:
        """
        Return a volatility-adjusted position size.

        Args:
            df:                OHLCV DataFrame (must have ``close``, ``high``,
                               ``low`` columns).
            current_price:     Latest close / mid price.
            proposed_size_usd: Position size calculated by the strategy
                               before any volatility adjustment.
            account_balance:   Current account balance in USD.

        Returns:
            ``(adjusted_size_usd, VolatilitySizingResult)``
        """
        if proposed_size_usd <= 0 or account_balance <= 0 or current_price <= 0:
            result = VolatilitySizingResult(
                original_size_usd=proposed_size_usd,
                adjusted_size_usd=proposed_size_usd,
                size_multiplier=1.0,
                volatility_regime="UNKNOWN",
                atr_pct=0.0,
                method="passthrough",
                details={"reason": "invalid_inputs"},
            )
            return proposed_size_usd, result

        # ----------------------------------------------------------------
        # Path A: use full VolatilityAdaptiveSizer when available
        # ----------------------------------------------------------------
        if self._sizer is not None:
            try:
                # base_size_pct is the fraction the strategy is requesting
                requested_pct = proposed_size_usd / account_balance
                adjusted_usd, details = self._sizer.calculate_position_size(
                    df=df,
                    account_balance=account_balance,
                    current_price=current_price,
                    base_size_pct=requested_pct,
                )
                regime = details.get("volatility_regime", "NORMAL")
                atr_pct = details.get("volatility_pct", 0.0)
                multiplier = adjusted_usd / proposed_size_usd if proposed_size_usd > 0 else 1.0
                result = VolatilitySizingResult(
                    original_size_usd=proposed_size_usd,
                    adjusted_size_usd=adjusted_usd,
                    size_multiplier=multiplier,
                    volatility_regime=regime,
                    atr_pct=atr_pct,
                    method="adaptive",
                    details=details,
                )
                self._log_result(result)
                return adjusted_usd, result
            except Exception as exc:
                logger.warning(
                    f"VolatilityPositionSizer: adaptive path failed ({exc}), "
                    "using built-in fallback"
                )

        # ----------------------------------------------------------------
        # Path B: built-in ATR fallback
        # ----------------------------------------------------------------
        atr_pct, regime = self._builtin_atr_regime(df, current_price)
        vol_multiplier = (
            self.target_volatility_pct / atr_pct
            if atr_pct > 0
            else 1.0
        )
        # Clamp the multiplier to a sensible range
        vol_multiplier = max(0.25, min(2.0, vol_multiplier))

        # Apply regime safety cap
        regime_cap = _REGIME_CAPS.get(regime, 1.0) if self.enable_regime_cap else 1.0
        combined_multiplier = vol_multiplier * regime_cap

        # Compute new size
        adjusted_usd = proposed_size_usd * combined_multiplier

        # Enforce account-balance bounds
        min_usd = account_balance * self.min_position_pct
        max_usd = account_balance * self.max_position_pct
        adjusted_usd = max(min_usd, min(max_usd, adjusted_usd))

        final_multiplier = adjusted_usd / proposed_size_usd if proposed_size_usd > 0 else 1.0

        result = VolatilitySizingResult(
            original_size_usd=proposed_size_usd,
            adjusted_size_usd=adjusted_usd,
            size_multiplier=final_multiplier,
            volatility_regime=regime,
            atr_pct=atr_pct,
            method="fallback",
            details={
                "vol_multiplier": vol_multiplier,
                "regime_cap": regime_cap,
                "combined_multiplier": combined_multiplier,
            },
        )
        self._log_result(result)
        return adjusted_usd, result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _builtin_atr_regime(
        self, df: pd.DataFrame, current_price: float
    ) -> Tuple[float, str]:
        """
        Compute a basic ATR percentage and detect the volatility regime.

        Returns:
            ``(atr_pct, regime_label)``
        """
        min_bars = self.atr_period + 1
        if df is None or len(df) < min_bars:
            return 0.0, "NORMAL"

        try:
            high = df["high"].values
            low = df["low"].values
            close = df["close"].values

            n = self.atr_period
            # True range (vectorised)
            tr = []
            for i in range(1, len(close)):
                tr.append(max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                ))
            if not tr:
                return 0.0, "NORMAL"

            # Simple mean of last n values
            recent_tr = tr[-n:]
            atr_value = sum(recent_tr) / len(recent_tr)
            atr_pct = (atr_value / current_price) * 100.0 if current_price > 0 else 0.0

            regime = "NORMAL"
            for label, (lo, hi) in _REGIME_THRESHOLDS.items():
                if lo <= atr_pct < hi:
                    regime = label
                    break

            return atr_pct, regime
        except Exception as exc:
            logger.debug(f"VolatilityPositionSizer._builtin_atr_regime error: {exc}")
            return 0.0, "NORMAL"

    @staticmethod
    def _log_result(result: "VolatilitySizingResult") -> None:
        if result.size_multiplier < 0.80 or result.size_multiplier > 1.20:
            logger.info(
                f"   📐 VolatilityPositionSizing: "
                f"${result.original_size_usd:.2f} → ${result.adjusted_size_usd:.2f} "
                f"({result.size_multiplier:.2f}x) "
                f"regime={result.volatility_regime} "
                f"atr={result.atr_pct:.2f}%"
            )
        else:
            logger.debug(str(result))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_SIZER_INSTANCE: Optional[VolatilityPositionSizer] = None


def get_volatility_position_sizer(**kwargs) -> VolatilityPositionSizer:
    """
    Return the global singleton :class:`VolatilityPositionSizer`.

    The first call creates the instance (with any supplied keyword
    arguments as configuration overrides); subsequent calls ignore the
    arguments and return the cached instance.
    """
    global _SIZER_INSTANCE
    if _SIZER_INSTANCE is None:
        _SIZER_INSTANCE = VolatilityPositionSizer(**kwargs)
    return _SIZER_INSTANCE
