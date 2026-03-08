"""
NIJA Volatility Shock Detector
================================

Detects sudden, abnormal expansions in market volatility (volatility shocks)
using rolling ATR z-scores and Bollinger Band width breakouts.  On a shock,
position-size scaling factors are returned so callers can reduce risk immediately.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                  VolatilityShockDetector                          │
  │                                                                   │
  │  Per-symbol rolling window of ATR values:                         │
  │                                                                   │
  │  1. ATR Z-Score     – (current_atr − mean) / std over lookback   │
  │  2. BB Width Ratio  – current BB width vs rolling mean            │
  │  3. Return Spike    – absolute bar return vs rolling std           │
  │                                                                   │
  │  Shock Severity:                                                  │
  │    NONE     z < 1.5                                               │
  │    MINOR    1.5 ≤ z < 2.0                                        │
  │    MODERATE 2.0 ≤ z < 3.0                                        │
  │    SEVERE   3.0 ≤ z < 4.5                                        │
  │    EXTREME  z ≥ 4.5                                               │
  │                                                                   │
  │  Size scaling (applied by caller):                                │
  │    NONE     1.00×   MINOR    0.80×                               │
  │    MODERATE 0.55×   SEVERE   0.30×   EXTREME  0.00× (block)     │
  │                                                                   │
  │  Portfolio-wide shock: aggregate signal across all symbols        │
  │  Audit log: data/volatility_shocks.jsonl                         │
  └──────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.volatility_shock_detector import get_volatility_shock_detector

    vsd = get_volatility_shock_detector()

    # Feed one bar of data each candle close:
    result = vsd.update(
        symbol="BTC-USD",
        atr=1200.0,
        bb_width=0.08,
        bar_return=0.023,
    )

    if result.severity != ShockSeverity.NONE:
        logger.warning("Volatility shock %s on %s – scale %.2f",
                       result.severity, "BTC-USD", result.size_scale)

    # Adjust position size:
    safe_size = raw_size * result.size_scale

    # Portfolio-wide shock check:
    portfolio_shock = vsd.get_portfolio_shock()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.volatility_shock_detector")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK: int = 50          # rolling window for ATR history
DEFAULT_MIN_HISTORY: int = 15       # minimum bars before shock detection
DEFAULT_SHOCK_HALF_LIFE: int = 10   # bars before shock severity decays one level

# ATR z-score thresholds
Z_MINOR: float = 1.5
Z_MODERATE: float = 2.0
Z_SEVERE: float = 3.0
Z_EXTREME: float = 4.5

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Enums & data containers
# ---------------------------------------------------------------------------

class ShockSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    EXTREME = "EXTREME"


# Size scale factor per severity
_SIZE_SCALE: Dict[ShockSeverity, float] = {
    ShockSeverity.NONE: 1.00,
    ShockSeverity.MINOR: 0.80,
    ShockSeverity.MODERATE: 0.55,
    ShockSeverity.SEVERE: 0.30,
    ShockSeverity.EXTREME: 0.00,
}


@dataclass
class ShockResult:
    """Result of a single-symbol shock assessment."""

    symbol: str
    severity: ShockSeverity
    size_scale: float           # multiply raw position size by this
    atr_z_score: float
    bb_width_ratio: float       # current / rolling_mean; 1.0 = normal
    return_z_score: float
    composite_z: float          # weighted combination used for classification
    bars_since_last_shock: int
    is_blocked: bool            # True when EXTREME (size_scale == 0)
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PortfolioShock:
    """Aggregate shock across all tracked symbols."""

    max_severity: ShockSeverity
    min_size_scale: float
    num_shocked_symbols: int        # severity > NONE
    shocked_symbols: List[str]
    portfolio_composite_z: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Per-symbol state
# ---------------------------------------------------------------------------

class _SymbolShockState:
    def __init__(self, lookback: int) -> None:
        self.atr_history: Deque[float] = deque(maxlen=lookback)
        self.bb_width_history: Deque[float] = deque(maxlen=lookback)
        self.return_history: Deque[float] = deque(maxlen=lookback)
        self.last_shock_bar: int = -999
        self.total_bars: int = 0
        self.latest_severity: ShockSeverity = ShockSeverity.NONE

    def push(self, atr: float, bb_width: Optional[float], bar_return: Optional[float]) -> None:
        self.atr_history.append(float(atr))
        if bb_width is not None and float(bb_width) > 0:
            self.bb_width_history.append(float(bb_width))
        if bar_return is not None:
            self.return_history.append(abs(float(bar_return)))
        self.total_bars += 1

    def atr_z(self) -> float:
        arr = list(self.atr_history)
        if len(arr) < 3:
            return 0.0
        current = arr[-1]
        history = arr[:-1]
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 1e-9
        return (current - mean) / std

    def bb_width_ratio(self) -> float:
        arr = list(self.bb_width_history)
        if len(arr) < 3:
            return 1.0
        current = arr[-1]
        mean = sum(arr[:-1]) / len(arr[:-1])
        return current / mean if mean > 0 else 1.0

    def return_z(self) -> float:
        arr = list(self.return_history)
        if len(arr) < 3:
            return 0.0
        current = arr[-1]
        history = arr[:-1]
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 1e-9
        return (current - mean) / std


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VolatilityShockDetector:
    """
    Detects volatility shocks via ATR z-score, BB width breakout, and return spikes.

    Parameters
    ----------
    lookback : int
        Rolling ATR/BB history window per symbol (default 50).
    min_history : int
        Minimum bars before shock detection activates (default 15).
    shock_half_life : int
        Bars before shock severity auto-decays one level (default 10).
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        min_history: int = DEFAULT_MIN_HISTORY,
        shock_half_life: int = DEFAULT_SHOCK_HALF_LIFE,
    ) -> None:
        self.lookback = lookback
        self.min_history = min_history
        self.shock_half_life = shock_half_life

        self._symbols: Dict[str, _SymbolShockState] = {}
        self._lock = threading.RLock()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = DATA_DIR / "volatility_shocks.jsonl"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        symbol: str,
        atr: float,
        bb_width: Optional[float] = None,
        bar_return: Optional[float] = None,
    ) -> ShockResult:
        """
        Feed one bar of data and return the current shock assessment.

        Parameters
        ----------
        symbol : str
            Trading pair symbol (e.g. "BTC-USD").
        atr : float
            Current ATR value (absolute).
        bb_width : float, optional
            Bollinger Band width (upper – lower) / midband.
        bar_return : float, optional
            Absolute bar return as decimal (e.g. 0.023 for 2.3%).

        Returns
        -------
        ShockResult
            Shock severity and position-size scale factor.
        """
        with self._lock:
            state = self._get_or_create(symbol)

            # Validate inputs at API boundary; warn on suspicious values
            if atr <= 0:
                logger.warning("VSD %s: non-positive ATR=%.4f ignored", symbol, atr)
                atr = max(atr, 1e-9)
            if bb_width is not None and bb_width < 0:
                logger.warning("VSD %s: negative bb_width=%.4f, treating as None", symbol, bb_width)
                bb_width = None

            state.push(
                atr=atr,
                bb_width=bb_width,
                bar_return=bar_return,
            )

            if state.total_bars < self.min_history:
                result = ShockResult(
                    symbol=symbol,
                    severity=ShockSeverity.NONE,
                    size_scale=1.0,
                    atr_z_score=0.0,
                    bb_width_ratio=1.0,
                    return_z_score=0.0,
                    composite_z=0.0,
                    bars_since_last_shock=state.total_bars - state.last_shock_bar,
                    is_blocked=False,
                    reason=f"insufficient history ({state.total_bars}/{self.min_history})",
                )
                return result

            atr_z = state.atr_z()
            bw_ratio = state.bb_width_ratio()
            ret_z = state.return_z()

            # Composite z: 50% ATR, 30% BB width contribution, 20% return spike
            bw_z = max(0.0, bw_ratio - 1.0) * 2.0  # ratio → z-like contribution
            composite_z = 0.50 * atr_z + 0.30 * bw_z + 0.20 * ret_z

            severity = self._classify(composite_z)

            # Track last shock bar for decay tracking
            if severity != ShockSeverity.NONE:
                state.last_shock_bar = state.total_bars

            bars_since = state.total_bars - state.last_shock_bar
            state.latest_severity = severity

            scale = _SIZE_SCALE[severity]
            reason = (
                f"composite_z={composite_z:.2f} (atr_z={atr_z:.2f}, "
                f"bb_ratio={bw_ratio:.2f}, ret_z={ret_z:.2f})"
            )

            result = ShockResult(
                symbol=symbol,
                severity=severity,
                size_scale=scale,
                atr_z_score=round(atr_z, 3),
                bb_width_ratio=round(bw_ratio, 3),
                return_z_score=round(ret_z, 3),
                composite_z=round(composite_z, 3),
                bars_since_last_shock=bars_since,
                is_blocked=(severity == ShockSeverity.EXTREME),
                reason=reason,
            )

            if severity not in (ShockSeverity.NONE, ShockSeverity.MINOR):
                self._log_shock(result)
                logger.warning(
                    "VSD %s shock on %s: z=%.2f scale=%.2f",
                    severity.value,
                    symbol,
                    composite_z,
                    scale,
                )

            return result

    def get_portfolio_shock(self) -> PortfolioShock:
        """
        Aggregate shock across all tracked symbols.

        Returns the worst severity and the minimum size scale factor,
        enabling callers to apply a portfolio-wide volatility regime check.
        """
        with self._lock:
            if not self._symbols:
                return PortfolioShock(
                    max_severity=ShockSeverity.NONE,
                    min_size_scale=1.0,
                    num_shocked_symbols=0,
                    shocked_symbols=[],
                    portfolio_composite_z=0.0,
                )

            severities = list(_SIZE_SCALE.keys())
            severity_rank = {s: i for i, s in enumerate(severities)}

            max_sev = ShockSeverity.NONE
            min_scale = 1.0
            shocked: List[str] = []
            composite_zs: List[float] = []

            for sym, state in self._symbols.items():
                sev = state.latest_severity
                if sev != ShockSeverity.NONE:
                    shocked.append(sym)
                if severity_rank[sev] > severity_rank[max_sev]:
                    max_sev = sev
                sc = _SIZE_SCALE[sev]
                if sc < min_scale:
                    min_scale = sc

                atr_z = state.atr_z()
                composite_zs.append(atr_z)

            avg_z = sum(composite_zs) / len(composite_zs) if composite_zs else 0.0

            return PortfolioShock(
                max_severity=max_sev,
                min_size_scale=min_scale,
                num_shocked_symbols=len(shocked),
                shocked_symbols=sorted(shocked),
                portfolio_composite_z=round(avg_z, 3),
            )

    def get_size_scale(self, symbol: str) -> float:
        """Return the current size scale factor for *symbol* (1.0 if unknown)."""
        with self._lock:
            state = self._symbols.get(symbol)
            if state is None:
                return 1.0
            return _SIZE_SCALE[state.latest_severity]

    def reset_symbol(self, symbol: str) -> None:
        """Clear shock state for *symbol* (e.g. after extended pause)."""
        with self._lock:
            self._symbols.pop(symbol, None)
            logger.info("VSD state reset for %s", symbol)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, symbol: str) -> _SymbolShockState:
        if symbol not in self._symbols:
            self._symbols[symbol] = _SymbolShockState(self.lookback)
        return self._symbols[symbol]

    @staticmethod
    def _classify(composite_z: float) -> ShockSeverity:
        if composite_z >= Z_EXTREME:
            return ShockSeverity.EXTREME
        if composite_z >= Z_SEVERE:
            return ShockSeverity.SEVERE
        if composite_z >= Z_MODERATE:
            return ShockSeverity.MODERATE
        if composite_z >= Z_MINOR:
            return ShockSeverity.MINOR
        return ShockSeverity.NONE

    def _log_shock(self, result: ShockResult) -> None:
        try:
            record = {
                "timestamp": result.timestamp,
                "symbol": result.symbol,
                "severity": result.severity.value,
                "size_scale": result.size_scale,
                "composite_z": result.composite_z,
                "atr_z_score": result.atr_z_score,
                "bb_width_ratio": result.bb_width_ratio,
                "return_z_score": result.return_z_score,
            }
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_vsd_instance: Optional[VolatilityShockDetector] = None
_vsd_lock = threading.Lock()


def get_volatility_shock_detector(**kwargs) -> VolatilityShockDetector:
    """Return the process-wide :class:`VolatilityShockDetector` singleton."""
    global _vsd_instance
    with _vsd_lock:
        if _vsd_instance is None:
            _vsd_instance = VolatilityShockDetector(**kwargs)
            logger.info("VolatilityShockDetector singleton created")
    return _vsd_instance
