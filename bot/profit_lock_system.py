"""
NIJA Profit Lock System
========================

A high-level **unified façade** that wires together every profit-protection
layer in the NIJA bot:

1. **ProfitHarvestLayer** — ratchet-floor stops + tier-based partial harvests
   (internally wraps ProfitLockEngine).
2. **ProfitExtractionEngine** — auto-withdrawal of accumulated profits to
   configurable destinations (bank, stablecoins, treasury wallet).
3. **WeeklySalaryMode** — fixed weekly payout ($1 250/week default) paid only
   when the system is profitable; smooths operator income into predictable
   real-life cash flow.

Why a façade?
-------------
The two subsystems already work independently.  This module provides a single
"register / update / close" lifecycle API so ``TradingStrategy`` (and any
other component) never has to import both engines separately.

Lifecycle
---------
::

  system = get_profit_lock_system()

  # 1. Position opens:
  system.register_position("BTC-USD", side="long",
                            entry_price=50_000.0, position_size_usd=1_000.0)

  # 2. Every price tick:
  action = system.update_position("BTC-USD", current_price=51_500.0)
  if action == "close":
      execute_market_close("BTC-USD")

  # 3. Trade closes (profit or loss):
  system.record_closed_profit("BTC-USD", pnl_usd=+120.0)

  # 4. Dashboard:
  print(system.get_report())

Thread Safety
-------------
All public methods delegate to the underlying engines which are themselves
thread-safe singletons.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("nija.profit_lock_system")

# ---------------------------------------------------------------------------
# Optional subsystem imports – degrade gracefully if a layer is missing
# ---------------------------------------------------------------------------

try:
    from bot.profit_harvest_layer import get_profit_harvest_layer, ProfitHarvestLayer
    _HARVEST_AVAILABLE = True
except ImportError:
    try:
        from profit_harvest_layer import get_profit_harvest_layer, ProfitHarvestLayer  # type: ignore
        _HARVEST_AVAILABLE = True
    except ImportError:
        get_profit_harvest_layer = None  # type: ignore
        ProfitHarvestLayer = None  # type: ignore
        _HARVEST_AVAILABLE = False
        logger.warning("ProfitHarvestLayer not available — ratchet-tier locking disabled")

try:
    from bot.profit_extraction_engine import get_profit_extraction_engine, ProfitExtractionEngine
    _EXTRACTION_AVAILABLE = True
except ImportError:
    try:
        from profit_extraction_engine import get_profit_extraction_engine, ProfitExtractionEngine  # type: ignore
        _EXTRACTION_AVAILABLE = True
    except ImportError:
        get_profit_extraction_engine = None  # type: ignore
        ProfitExtractionEngine = None  # type: ignore
        _EXTRACTION_AVAILABLE = False
        logger.warning("ProfitExtractionEngine not available — auto-withdrawal disabled")


# ---------------------------------------------------------------------------
# ProfitLockSystem
# ---------------------------------------------------------------------------

class ProfitLockSystem:
    """
    Unified profit-lock façade for NIJA.

    Combines per-trade ratchet stops + automatic gain harvesting
    (``ProfitHarvestLayer``) with portfolio-level auto-withdrawal to
    external destinations (``ProfitExtractionEngine``).

    Obtain the singleton via ``get_profit_lock_system()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # --- Ratchet-tier harvest layer ---
        if _HARVEST_AVAILABLE and get_profit_harvest_layer is not None:
            try:
                self._harvest: Optional[ProfitHarvestLayer] = get_profit_harvest_layer()
                logger.info("✅ ProfitLockSystem: ratchet-tier harvest layer active")
            except Exception as exc:
                logger.warning("ProfitLockSystem: harvest layer init failed – %s", exc)
                self._harvest = None
        else:
            self._harvest = None

        # --- Auto-withdrawal / extraction engine ---
        if _EXTRACTION_AVAILABLE and get_profit_extraction_engine is not None:
            try:
                self._extraction: Optional[ProfitExtractionEngine] = get_profit_extraction_engine()
                logger.info("✅ ProfitLockSystem: auto-withdrawal extraction engine active")
            except Exception as exc:
                logger.warning("ProfitLockSystem: extraction engine init failed – %s", exc)
                self._extraction = None
        else:
            self._extraction = None

        _active = sum([self._harvest is not None, self._extraction is not None])
        logger.info(
            "🔒 ProfitLockSystem initialised (%d/%d subsystems active: harvest=%s, extraction=%s)",
            _active, 2,
            "✓" if self._harvest else "✗",
            "✓" if self._extraction else "✗",
        )

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def register_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        position_size_usd: float = 0.0,
    ) -> None:
        """
        Register a new open position so the system can track it for
        ratchet-floor stops and tier-based harvests.

        Args:
            symbol:             Trading pair (e.g. "BTC-USD").
            side:               "long" or "short".
            entry_price:        Fill price at entry.
            position_size_usd:  Notional size of the position in USD.
        """
        if self._harvest is not None:
            try:
                self._harvest.register_position(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    position_size_usd=position_size_usd,
                )
                logger.debug(
                    "ProfitLockSystem: registered %s %s @ %.4f ($%.2f)",
                    side.upper(), symbol, entry_price, position_size_usd,
                )
            except Exception as exc:
                logger.warning("ProfitLockSystem.register_position failed for %s: %s", symbol, exc)

    def update_position(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Process a price update for an open position.

        Returns ``"close"`` if the ratchet floor has been hit (signalling the
        caller to execute a market close); otherwise returns ``None``.

        Any tier-based harvest events are handled internally and routed to
        the PortfolioProfitEngine.

        Args:
            symbol:        Trading pair.
            current_price: Latest market price.
        """
        if self._harvest is None:
            return None
        try:
            decision = self._harvest.process_price_update(symbol, current_price)
            if decision is None:
                return None
            if decision.harvest_triggered and decision.harvest_amount_usd > 0:
                logger.info(
                    "💰 ProfitLockSystem: harvested $%.2f from %s (tier=%s, cumulative=$%.2f)",
                    decision.harvest_amount_usd,
                    symbol,
                    decision.current_tier,
                    decision.cumulative_harvested_usd,
                )
            if decision.floor_hit:
                logger.info(
                    "🔒 ProfitLockSystem: ratchet floor hit for %s — signalling close",
                    symbol,
                )
                return "close"
        except Exception as exc:
            logger.warning("ProfitLockSystem.update_position failed for %s: %s", symbol, exc)
        return None

    def record_closed_profit(self, symbol: str, pnl_usd: float) -> None:
        """
        Record realised profit (or loss) after a position closes.

        Winning trades are forwarded to the ``ProfitExtractionEngine`` which
        accumulates gains and auto-withdraws them once the configured
        threshold is reached.

        The position is also removed from the harvest layer's tracking.

        Args:
            symbol:   Trading pair.
            pnl_usd:  Realised profit (+) or loss (−) in USD.
        """
        # Always clean up harvest tracking
        if self._harvest is not None:
            try:
                self._harvest.remove_position(symbol)
            except Exception as exc:
                logger.debug("ProfitLockSystem.remove_position failed for %s: %s", symbol, exc)

        # Only forward profits to the extraction engine
        if pnl_usd > 0 and self._extraction is not None:
            try:
                pool = self._extraction.record_profit(
                    symbol=symbol,
                    pnl_usd=pnl_usd,
                    note=f"closed trade profit: {symbol}",
                    auto_extract=True,
                )
                logger.info(
                    "💵 ProfitLockSystem: recorded $%.2f profit from %s (extraction pool=$%.2f)",
                    pnl_usd, symbol, pool,
                )
            except Exception as exc:
                logger.warning("ProfitLockSystem.record_closed_profit failed for %s: %s", symbol, exc)

    def remove_position(self, symbol: str) -> None:
        """
        Remove a position from the harvest layer without recording profit.

        Use this when a position closes at a loss or when the caller has
        already called ``record_closed_profit``.
        """
        if self._harvest is not None:
            try:
                self._harvest.remove_position(symbol)
            except Exception as exc:
                logger.debug("ProfitLockSystem.remove_position failed for %s: %s", symbol, exc)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a combined status report from all active subsystems."""
        lines: list[str] = [
            "=" * 70,
            "🔒  PROFIT LOCK SYSTEM — STATUS REPORT",
            "=" * 70,
        ]

        if self._harvest is not None:
            try:
                lines.append(self._harvest.get_report())
            except Exception as exc:
                lines.append(f"[HarvestLayer report error: {exc}]")
        else:
            lines.append("  ⚠️  Ratchet-tier harvest layer: NOT AVAILABLE")

        if self._extraction is not None:
            try:
                lines.append(self._extraction.get_report())
            except Exception as exc:
                lines.append(f"[ExtractionEngine report error: {exc}]")
        else:
            lines.append("  ⚠️  Auto-withdrawal extraction engine: NOT AVAILABLE")

        lines.append("=" * 70)
        return "\n".join(lines)

    @property
    def harvest_layer(self) -> Optional["ProfitHarvestLayer"]:
        """Direct access to the underlying ProfitHarvestLayer (read-only)."""
        return self._harvest

    @property
    def extraction_engine(self) -> Optional["ProfitExtractionEngine"]:
        """Direct access to the underlying ProfitExtractionEngine (read-only)."""
        return self._extraction


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_SYSTEM_INSTANCE: Optional[ProfitLockSystem] = None
_SYSTEM_LOCK = threading.Lock()


def get_profit_lock_system() -> ProfitLockSystem:
    """
    Return the process-wide singleton ``ProfitLockSystem``.

    Thread-safe; the instance is created once on first call.
    """
    global _SYSTEM_INSTANCE
    if _SYSTEM_INSTANCE is None:
        with _SYSTEM_LOCK:
            if _SYSTEM_INSTANCE is None:
                _SYSTEM_INSTANCE = ProfitLockSystem()
    return _SYSTEM_INSTANCE
