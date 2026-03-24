"""
DYNAMIC MIN ENTRY SIZER
=======================
Raises the minimum position size required to open a new trade based on two
real-time market factors:

1. **Volatility (ATR%)**: In a choppy/high-ATR environment the price can
   swing by more than the typical stop-loss offset before the trade reaches
   its target.  A position that starts at $10 and drops 40% (ATR = 40%)
   before the SL triggers is worth only $6 — barely above the dust threshold.
   The volatility floor ensures the position cannot fall below
   ``dust_threshold_usd`` after a worst-case 1×ATR adverse move.

2. **Fee pressure (round-trip fee %)**: When fees are elevated (e.g. on a
   new account tier, during a rate-change period, or when spread widens) the
   break-even hurdle rises.  The fee floor scales the base minimum
   proportionally so round-trip costs remain a manageable fraction of the
   expected profit.

Formula
-------
::

    volatility_floor = dust_threshold_usd / (1 − min(atr_pct × vol_mult, 0.90))
    fee_factor       = max(1.0, fee_pct_roundtrip / REFERENCE_FEE_PCT)
    fee_floor        = base_min_usd × fee_factor
    dynamic_min      = max(base_min_usd, volatility_floor, fee_floor)

The result is capped at ``max_min_usd`` (default 3× base) so the sizer never
produces an absurdly large minimum that would prevent all entries.

Usage
-----
::

    from bot.dynamic_min_entry_sizer import get_dynamic_min_entry_sizer

    sizer = get_dynamic_min_entry_sizer()
    min_usd = sizer.get_min_entry_usd(
        base_min_usd=10.0,
        atr_pct=0.04,          # 4% ATR
        fee_pct_roundtrip=0.014,  # 1.4% round-trip
    )
    if position_size < min_usd:
        continue  # skip entry

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nija.dynamic_min_entry_sizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Baseline round-trip fee used as the reference for the fee multiplier.
# At this fee rate the multiplier is exactly 1.0 (no change to base_min).
# Coinbase Advanced Trade taker fees for entry + exit: ~0.006 + 0.006 = 0.012.
REFERENCE_FEE_PCT: float = 0.012

# A position that drops by ATR% before the SL fires will be worth
# position_size × (1 − atr_pct).  We apply a conservatism multiplier so that
# even partial adverse moves (not a full ATR) raise the floor meaningfully.
DEFAULT_VOL_MULT: float = 1.5

# Dust threshold in USD.  Aligns with auto_dust_sweeper.DEFAULT_DUST_THRESHOLD_USD.
DEFAULT_DUST_THRESHOLD_USD: float = 5.0

# Cap: the dynamic minimum cannot exceed this multiple of base_min_usd.
# Prevents the sizer from blocking all entries in extreme vol environments.
DEFAULT_MAX_MULTIPLIER: float = 3.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MinEntrySizerResult:
    """Detailed breakdown of a single get_min_entry_usd call."""
    base_min_usd: float
    atr_pct: float
    fee_pct_roundtrip: float
    volatility_floor: float
    fee_floor: float
    dynamic_min_usd: float
    binding_factor: str   # "base" | "volatility" | "fee" | "cap"


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class DynamicMinEntrySizer:
    """
    Computes a dynamic minimum position size (in USD) that accounts for
    current market volatility and fee pressure.
    """

    def __init__(
        self,
        vol_mult: float = DEFAULT_VOL_MULT,
        dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
        max_multiplier: float = DEFAULT_MAX_MULTIPLIER,
        reference_fee_pct: float = REFERENCE_FEE_PCT,
        enabled: bool = True,
    ) -> None:
        self.vol_mult = vol_mult
        self.dust_threshold_usd = dust_threshold_usd
        self.max_multiplier = max_multiplier
        self.reference_fee_pct = reference_fee_pct
        self.enabled = enabled
        logger.info(
            "📐 DynamicMinEntrySizer initialised | vol_mult=%.1f× | "
            "dust_threshold=$%.2f | max_mult=%.1f× | ref_fee=%.2f%%",
            vol_mult,
            dust_threshold_usd,
            max_multiplier,
            reference_fee_pct * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_min_entry_usd(
        self,
        base_min_usd: float,
        atr_pct: float,
        fee_pct_roundtrip: float,
        dust_threshold_usd: Optional[float] = None,
    ) -> float:
        """
        Return the minimum position size (USD) required for this entry.

        Args:
            base_min_usd:       Balance-/broker-derived base minimum (e.g. $10).
            atr_pct:            Current ATR as a fraction of price (e.g. 0.04 = 4%).
                                Pass 0.0 when ATR is unknown to use only the fee floor.
            fee_pct_roundtrip:  Total round-trip fees as a fraction (entry + exit
                                combined, e.g. 0.014 = 1.4%).
            dust_threshold_usd: Override the instance dust threshold.

        Returns:
            Minimum USD position size (≥ ``base_min_usd``).
        """
        if not self.enabled:
            return base_min_usd

        dust = dust_threshold_usd if dust_threshold_usd is not None else self.dust_threshold_usd

        # ── 1. Volatility floor ────────────────────────────────────────
        # Ensure position_usd × (1 − effective_atr) ≥ dust_threshold_usd
        # => position_usd ≥ dust_threshold_usd / (1 − effective_atr)
        # effective_atr is capped at 0.90, so the denominator is at least 0.10;
        # abs() guards against unexpected edge cases if the cap is ever changed.
        effective_atr = min(atr_pct * self.vol_mult, 0.90)
        if effective_atr > 0:
            volatility_floor = dust / max(0.01, abs(1.0 - effective_atr))
        else:
            volatility_floor = base_min_usd

        # ── 2. Fee floor ───────────────────────────────────────────────
        # Scale base_min proportionally when fees exceed the reference rate.
        fee_factor = max(1.0, fee_pct_roundtrip / self.reference_fee_pct)
        fee_floor = base_min_usd * fee_factor

        # ── 3. Combined dynamic minimum ────────────────────────────────
        raw_min = max(base_min_usd, volatility_floor, fee_floor)

        # Cap: never raise more than max_multiplier × base
        capped_min = min(raw_min, base_min_usd * self.max_multiplier)

        # Determine which factor was binding (for logging / audit)
        if capped_min < raw_min:
            binding = "cap"
        elif raw_min == volatility_floor and volatility_floor > fee_floor:
            binding = "volatility"
        elif raw_min == fee_floor and fee_floor > base_min_usd:
            binding = "fee"
        else:
            binding = "base"

        result = MinEntrySizerResult(
            base_min_usd=base_min_usd,
            atr_pct=atr_pct,
            fee_pct_roundtrip=fee_pct_roundtrip,
            volatility_floor=volatility_floor,
            fee_floor=fee_floor,
            dynamic_min_usd=capped_min,
            binding_factor=binding,
        )

        if capped_min > base_min_usd:
            logger.debug(
                "📐 DynamicMinEntry raised: $%.2f → $%.2f "
                "(atr=%.2f%% vol_floor=$%.2f | fees=%.2f%% fee_floor=$%.2f | binding=%s)",
                base_min_usd,
                capped_min,
                atr_pct * 100,
                volatility_floor,
                fee_pct_roundtrip * 100,
                fee_floor,
                result.binding_factor,
            )

        return capped_min

    def get_detailed_result(
        self,
        base_min_usd: float,
        atr_pct: float,
        fee_pct_roundtrip: float,
        dust_threshold_usd: Optional[float] = None,
    ) -> MinEntrySizerResult:
        """Like get_min_entry_usd but also returns the breakdown dataclass."""
        dust = dust_threshold_usd if dust_threshold_usd is not None else self.dust_threshold_usd
        effective_atr = min(atr_pct * self.vol_mult, 0.90)
        volatility_floor = (dust / max(0.01, abs(1.0 - effective_atr))) if effective_atr > 0 else base_min_usd
        fee_factor = max(1.0, fee_pct_roundtrip / self.reference_fee_pct)
        fee_floor = base_min_usd * fee_factor
        raw_min = max(base_min_usd, volatility_floor, fee_floor)
        capped_min = min(raw_min, base_min_usd * self.max_multiplier)
        if capped_min < raw_min:
            binding = "cap"
        elif raw_min == volatility_floor and volatility_floor > fee_floor:
            binding = "volatility"
        elif raw_min == fee_floor and fee_floor > base_min_usd:
            binding = "fee"
        else:
            binding = "base"
        return MinEntrySizerResult(
            base_min_usd=base_min_usd,
            atr_pct=atr_pct,
            fee_pct_roundtrip=fee_pct_roundtrip,
            volatility_floor=volatility_floor,
            fee_floor=fee_floor,
            dynamic_min_usd=capped_min,
            binding_factor=binding,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[DynamicMinEntrySizer] = None


def get_dynamic_min_entry_sizer(
    vol_mult: float = DEFAULT_VOL_MULT,
    dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
    max_multiplier: float = DEFAULT_MAX_MULTIPLIER,
    reference_fee_pct: float = REFERENCE_FEE_PCT,
    enabled: bool = True,
) -> DynamicMinEntrySizer:
    """Return the process-wide singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = DynamicMinEntrySizer(
            vol_mult=vol_mult,
            dust_threshold_usd=dust_threshold_usd,
            max_multiplier=max_multiplier,
            reference_fee_pct=reference_fee_pct,
            enabled=enabled,
        )
    return _instance
