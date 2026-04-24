"""
NIJA Volatility-Weighted Capital Router
=========================================

Routes capital across symbols / strategies by **weighting each opportunity
inversely by its recent volatility**.  High-volatility symbols receive a
smaller slice of available capital; low-volatility symbols receive a larger
slice.  This mirrors professional risk-parity logic without requiring a full
covariance matrix.

Architecture
------------
::

  ┌────────────────────────────────────────────────────────────────────┐
  │              VolatilityWeightedCapitalRouter                       │
  │                                                                    │
  │  update_volatility(symbol, atr_pct)  ← call each bar              │
  │  allocate(total_usd, symbols)        → {symbol: usd}              │
  │  get_size_multiplier(symbol)         → float  [0.25 – 1.50]       │
  │  get_report()                        → Dict                       │
  └────────────────────────────────────────────────────────────────────┘

Volatility metric
-----------------
Each symbol's volatility is expressed as **ATR-as-percentage-of-price**
(ATR %).  Internally the router stores an EMA of recent readings to smooth
out single-bar spikes.

Allocation formula
------------------
::

  inv_vol_i  = 1 / max(ema_atr_pct_i, floor)
  weight_i   = inv_vol_i / sum(inv_vol_j for j in symbols)
  alloc_i    = total_usd × weight_i × regime_multiplier

Size-multiplier formula (single-symbol mode)
--------------------------------------------
When sizing a position for a symbol without a full basket:

  multiplier = clamp(median_vol / symbol_vol, min=0.25, max=1.50)

Usage
-----
::

    from bot.volatility_weighted_capital_router import (
        get_volatility_router,
    )

    router = get_volatility_router()

    # Feed latest ATR each bar (ATR % = ATR / close * 100):
    router.update_volatility("BTC-USD", atr_pct=1.20)
    router.update_volatility("ETH-USD", atr_pct=2.10)
    router.update_volatility("SOL-USD", atr_pct=3.50)

    # Basket allocation:
    allocations = router.allocate(
        total_usd=10_000.0,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
    )
    # → {"BTC-USD": 5_000, "ETH-USD": 3_000, "SOL-USD": 2_000}  (illustrative)

    # Single-symbol size multiplier (apply to base_position_usd):
    mult = router.get_size_multiplier("SOL-USD")  # e.g. 0.60 (volatile → smaller)
    position_usd = base_position_usd * mult

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.volatility_capital_router")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class VolatilityRouterConfig:
    """Tunable parameters for the volatility-weighted router."""
    ema_alpha: float = 0.20             # EMA smoothing for volatility readings
    vol_floor_pct: float = 0.05         # Minimum ATR % (prevents division by zero)
    min_size_multiplier: float = 0.25   # Smallest allowed size multiplier
    max_size_multiplier: float = 1.50   # Largest allowed size multiplier
    # Regime-driven global capital multipliers:
    regime_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "BULL_TRENDING":  1.00,
        "BULL_BREAKOUT":  0.90,
        "BEAR_TRENDING":  0.50,
        "BEAR_BREAKDOWN": 0.30,
        "SIDEWAYS":       0.70,
        "VOLATILE":       0.40,
        "RECOVERY":       0.60,
        "UNKNOWN":        0.60,
    })


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class VolatilityWeightedCapitalRouter:
    """
    Allocates capital inversely proportional to volatility.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self, config: Optional[VolatilityRouterConfig] = None) -> None:
        self._config = config or VolatilityRouterConfig()
        self._lock = threading.Lock()
        # EMA-smoothed ATR % per symbol
        self._ema_vol: Dict[str, float] = {}
        self._current_regime: str = "UNKNOWN"
        logger.info("✅ VolatilityWeightedCapitalRouter initialised")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def update_volatility(self, symbol: str, atr_pct: float) -> None:
        """
        Feed the latest ATR-as-percentage-of-price for *symbol*.

        Args:
            symbol:  Trading pair, e.g. "BTC-USD".
            atr_pct: ATR expressed as ``(ATR / close) * 100``.
        """
        if atr_pct < 0:
            logger.debug("VolatilityRouter: ignoring negative atr_pct %.4f for %s", atr_pct, symbol)
            return
        with self._lock:
            prev = self._ema_vol.get(symbol, atr_pct)
            alpha = self._config.ema_alpha
            self._ema_vol[symbol] = alpha * atr_pct + (1 - alpha) * prev

    def set_regime(self, regime: str) -> None:
        """Update the current market regime (affects global capital multiplier)."""
        with self._lock:
            self._current_regime = regime.upper()

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate(
        self,
        total_usd: float,
        symbols: List[str],
        regime: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Distribute *total_usd* across *symbols* inversely by volatility.

        Symbols with no recorded volatility receive the equal share before
        volatility weighting, using the current median volatility as a proxy.

        Args:
            total_usd: Total capital to distribute.
            symbols:   List of symbols to allocate to.
            regime:    Override current regime for this call only.

        Returns:
            Mapping of ``{symbol: allocated_usd}``.
        """
        if not symbols or total_usd <= 0:
            return {}

        regime_key = (regime or self._current_regime).upper()
        multiplier = self._config.regime_multipliers.get(
            regime_key, self._config.regime_multipliers["UNKNOWN"]
        )
        deployable = total_usd * multiplier

        with self._lock:
            vols = dict(self._ema_vol)

        floor = self._config.vol_floor_pct

        # Use current median for symbols we haven't seen yet
        known_vols = list(vols.values())
        median_vol = _median(known_vols) if known_vols else 1.0

        inv_vols: Dict[str, float] = {}
        for sym in symbols:
            v = max(vols.get(sym, median_vol), floor)
            inv_vols[sym] = 1.0 / v

        total_inv = sum(inv_vols.values())
        if total_inv <= 0:
            equal = deployable / len(symbols)
            return {s: equal for s in symbols}

        return {s: deployable * (inv_vols[s] / total_inv) for s in symbols}

    # ------------------------------------------------------------------
    # Single-symbol multiplier
    # ------------------------------------------------------------------

    def get_size_multiplier(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> float:
        """
        Return a position-size multiplier for *symbol* based on its
        relative volatility to the basket median.

        Values below 1.0 mean "reduce size" (high vol); above 1.0 mean
        "increase size" (low vol), capped by ``max_size_multiplier``.

        Additionally applies a regime-level scaling factor.
        """
        with self._lock:
            vols = dict(self._ema_vol)
            regime_key = (regime or self._current_regime).upper()

        regime_mult = self._config.regime_multipliers.get(
            regime_key, self._config.regime_multipliers["UNKNOWN"]
        )

        floor = self._config.vol_floor_pct
        sym_vol = max(vols.get(symbol, None) or _median(list(vols.values())) or 1.0, floor)

        known_vols = [v for v in vols.values() if v > 0]
        median_vol = max(_median(known_vols) if known_vols else sym_vol, floor)

        raw = median_vol / sym_vol
        clamped = max(
            self._config.min_size_multiplier,
            min(self._config.max_size_multiplier, raw),
        )
        return round(clamped * regime_mult, 4)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict:
        """Return a status dictionary for monitoring/logging."""
        with self._lock:
            vols = dict(self._ema_vol)
            regime = self._current_regime

        known = list(vols.values())
        return {
            "regime": regime,
            "regime_multiplier": self._config.regime_multipliers.get(regime, 0.6),
            "symbol_volatility": {k: round(v, 4) for k, v in vols.items()},
            "median_vol_pct": round(_median(known), 4) if known else 0.0,
            "symbol_count": len(vols),
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router_instance: Optional[VolatilityWeightedCapitalRouter] = None
_router_lock = threading.Lock()


def get_volatility_router(
    config: Optional[VolatilityRouterConfig] = None,
) -> VolatilityWeightedCapitalRouter:
    """Return the singleton VolatilityWeightedCapitalRouter."""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = VolatilityWeightedCapitalRouter(config=config)
    return _router_instance
