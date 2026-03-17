"""
NIJA Volatility Guard
======================

**Priority-1 gate** -- prevents blowups by blocking or scaling down trades
during abnormal volatility conditions.

Wraps :class:`VolatilityShockDetector` and exposes a simple boolean gate:

* ``EXTREME`` shock  -> hard block (``allowed=False``, ``size_scale=0.0``)
* ``SEVERE``  shock  -> allow with a 0.30x size multiplier (logged as warning)
* ``MODERATE`` shock -> allow with a 0.55x size multiplier
* ``MINOR``   shock  -> allow with a 0.80x size multiplier
* ``NONE``           -> allow with 1.00x (full size)

When no live ATR data has been fed for a symbol yet the guard passes through
(fail-open) so normal startup is not blocked.

Usage
-----
::

    from bot.volatility_guard import get_volatility_guard

    guard = get_volatility_guard()

    result = guard.check(symbol="BTC-USD")
    if not result.allowed:
        logger.warning("Trade blocked: %s", result.reason)
        return

    size_usd *= result.size_scale      # reduce size when volatility is high

    # Feed live bar data each candle so the detector stays calibrated
    guard.update(symbol="BTC-USD", atr=1_200.0, bb_width=0.08, bar_return=0.023)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nija.volatility_guard")

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class VolatilityGuardResult:
    """Decision returned by :class:`VolatilityGuard.check`."""

    allowed: bool
    size_scale: float           # 0.0 = blocked; 1.0 = full size
    severity: str               # NONE / MINOR / MODERATE / SEVERE / EXTREME
    reason: str
    symbol: str = ""


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class VolatilityGuard:
    """Priority-1 gate: blocks / scales trades on volatility shock.

    Thread-safe singleton via ``get_volatility_guard()``.
    """

    def __init__(self, block_on_severe: bool = False) -> None:
        """
        Parameters
        ----------
        block_on_severe:
            If ``True``, SEVERE shocks (size_scale=0.30) are also fully
            blocked rather than merely scaled.  Default is ``False``.
        """
        self._block_on_severe = block_on_severe
        self._lock = threading.Lock()
        self._vsd = self._load_vsd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, symbol: Optional[str] = None) -> VolatilityGuardResult:
        """Evaluate whether a trade should be allowed given current volatility.

        Parameters
        ----------
        symbol:
            Trading symbol (e.g. ``"BTC-USD"``).  When *None* or empty, the
            portfolio-wide aggregate shock is used.

        Returns
        -------
        VolatilityGuardResult
            ``.allowed`` is ``False`` only on EXTREME (or SEVERE when
            ``block_on_severe=True``) shock.
        """
        vsd = self._vsd
        if vsd is None:
            # Fail-open: detector not available
            return VolatilityGuardResult(
                allowed=True,
                size_scale=1.0,
                severity="NONE",
                reason="VolatilityShockDetector unavailable -- passing through",
                symbol=symbol or "",
            )

        if symbol:
            return self._check_symbol(vsd, symbol)
        return self._check_portfolio(vsd)

    def update(
        self,
        symbol: str,
        atr: float,
        bb_width: Optional[float] = None,
        bar_return: Optional[float] = None,
    ) -> VolatilityGuardResult:
        """Feed one bar of data and return the updated shock assessment.

        Call this on every candle close **before** calling ``check()``.

        Parameters
        ----------
        symbol:
            Trading symbol.
        atr:
            Current Average True Range value.
        bb_width:
            Current Bollinger Band width (optional but improves accuracy).
        bar_return:
            Absolute bar return (``abs(close/prev_close - 1)``), optional.
        """
        vsd = self._vsd
        if vsd is None:
            return VolatilityGuardResult(
                allowed=True, size_scale=1.0, severity="NONE",
                reason="detector unavailable", symbol=symbol,
            )
        try:
            result = vsd.update(
                symbol=symbol,
                atr=atr,
                bb_width=bb_width,
                bar_return=bar_return,
            )
            return self._shock_result_to_guard(result)
        except Exception as exc:
            logger.warning("VolatilityGuard.update error: %s", exc)
            return VolatilityGuardResult(
                allowed=True, size_scale=1.0, severity="NONE",
                reason=f"update error: {exc}", symbol=symbol,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_symbol(self, vsd, symbol: str) -> VolatilityGuardResult:
        try:
            state = vsd._symbols.get(symbol)
            if state is None:
                # No data yet -- pass through
                return VolatilityGuardResult(
                    allowed=True, size_scale=1.0, severity="NONE",
                    reason="no data yet -- passing through", symbol=symbol,
                )
            severity = state.latest_severity
            size_scale = vsd.SIZE_SCALES.get(severity, 1.0)
            return self._make_result(symbol, severity.value if hasattr(severity, 'value') else str(severity), size_scale)
        except Exception as exc:
            logger.warning("VolatilityGuard symbol check error: %s", exc)
            return VolatilityGuardResult(
                allowed=True, size_scale=1.0, severity="NONE",
                reason=f"check error: {exc}", symbol=symbol,
            )

    def _check_portfolio(self, vsd) -> VolatilityGuardResult:
        try:
            shock = vsd.get_portfolio_shock()
            severity_str = (
                shock.max_severity.value
                if hasattr(shock.max_severity, 'value')
                else str(shock.max_severity)
            )
            size_scale = shock.min_size_scale
            return self._make_result("PORTFOLIO", severity_str, size_scale)
        except Exception as exc:
            logger.warning("VolatilityGuard portfolio check error: %s", exc)
            return VolatilityGuardResult(
                allowed=True, size_scale=1.0, severity="NONE",
                reason=f"portfolio check error: {exc}", symbol="PORTFOLIO",
            )

    def _make_result(
        self, symbol: str, severity_str: str, size_scale: float
    ) -> VolatilityGuardResult:
        blocked = (
            size_scale == 0.0
            or (self._block_on_severe and severity_str == "SEVERE")
        )
        if blocked:
            reason = (
                f"Volatility shock {severity_str} on {symbol} -- "
                "trade BLOCKED to prevent blowup"
            )
            logger.warning("VolatilityGuard BLOCKED | %s | severity=%s", symbol, severity_str)
        elif size_scale < 1.0:
            reason = (
                f"Volatility shock {severity_str} on {symbol} -- "
                f"size scaled to {size_scale:.0%}"
            )
            logger.info("VolatilityGuard SCALED | %s | severity=%s | scale=%.2f",
                        symbol, severity_str, size_scale)
        else:
            reason = f"Volatility normal on {symbol}"

        return VolatilityGuardResult(
            allowed=not blocked,
            size_scale=0.0 if blocked else size_scale,
            severity=severity_str,
            reason=reason,
            symbol=symbol,
        )

    def _shock_result_to_guard(self, shock_result) -> VolatilityGuardResult:
        """Convert a ``ShockResult`` from the detector to a ``VolatilityGuardResult``."""
        severity_str = (
            shock_result.severity.value
            if hasattr(shock_result.severity, 'value')
            else str(shock_result.severity)
        )
        return self._make_result(
            shock_result.symbol, severity_str, shock_result.size_scale
        )

    @staticmethod
    def _load_vsd():
        """Load the VolatilityShockDetector singleton (graceful if absent)."""
        for mod_name in ("bot.volatility_shock_detector", "volatility_shock_detector"):
            try:
                mod = __import__(mod_name, fromlist=["get_volatility_shock_detector"])
                vsd = mod.get_volatility_shock_detector()
                # Expose SIZE_SCALES from the module if not on the object
                if not hasattr(vsd, 'SIZE_SCALES'):
                    try:
                        vsd.SIZE_SCALES = mod.SIZE_SCALES
                    except AttributeError:
                        pass
                logger.info("VolatilityGuard: detector loaded from %s", mod_name)
                return vsd
            except Exception as exc:
                logger.debug("VolatilityGuard: could not load %s: %s", mod_name, exc)
        logger.warning(
            "VolatilityGuard: VolatilityShockDetector unavailable -- guard is pass-through"
        )
        return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[VolatilityGuard] = None
_instance_lock = threading.Lock()


def get_volatility_guard(block_on_severe: bool = False) -> VolatilityGuard:
    """Return the process-wide :class:`VolatilityGuard` singleton.

    Parameters
    ----------
    block_on_severe:
        Only used on the first call; ignored on subsequent calls.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = VolatilityGuard(block_on_severe=block_on_severe)
    return _instance
