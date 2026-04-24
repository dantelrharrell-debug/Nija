"""
NIJA Cross-Broker Arbitrage Monitor
=====================================

Tracks live bid/ask prices across multiple brokers, detects meaningful
price divergences, and emits actionable signals so the trading engine can:

  * Prefer the venue with the most favourable fill price for a given side.
  * Flag symbol/direction pairs where a spread gap is exploitable.
  * Suppress entries when all venues show adverse pricing (e.g. during a
    flash-crash or thin-market episode).

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────────┐
  │              CrossBrokerArbitrageMonitor                        │
  │                                                                 │
  │  update_price(broker, symbol, bid, ask)  ← call each cycle     │
  │  get_best_venue(symbol, side)            → BrokerName | None   │
  │  get_spread_gap(symbol)                  → float (%)           │
  │  get_arb_signal(symbol)                  → ArbSignal           │
  │  get_report()                            → Dict                │
  └─────────────────────────────────────────────────────────────────┘

Arbitrage thresholds (configurable via ArbConfig)
--------------------------------------------------
* ``min_spread_gap_pct``  – minimum cross-broker spread to flag (default 0.10 %)
* ``strong_signal_pct``   – gap treated as "strong" arb opportunity (default 0.50 %)
* ``stale_price_seconds`` – discard prices older than this (default 30 s)

Usage
-----
::

    from bot.cross_broker_arbitrage_monitor import (
        get_arb_monitor, ArbSignalStrength
    )

    monitor = get_arb_monitor()

    # Populate after fetching ticker from each broker:
    monitor.update_price("coinbase", "BTC-USD", bid=68_400.0, ask=68_420.0)
    monitor.update_price("kraken",   "BTC-USD", bid=68_380.0, ask=68_395.0)

    signal = monitor.get_arb_signal("BTC-USD")
    if signal.strength == ArbSignalStrength.STRONG:
        # Use signal.best_buy_venue / signal.best_sell_venue
        place_trade(venue=signal.best_buy_venue)

    # Before opening a LONG: prefer cheapest ask
    best = monitor.get_best_venue("BTC-USD", side="buy")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.cross_broker_arb")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ArbConfig:
    """Tunable parameters for the arbitrage monitor."""
    min_spread_gap_pct: float = 0.10    # Minimum gap to flag (% of mid-price)
    strong_signal_pct: float = 0.50     # Gap treated as a strong arb signal
    stale_price_seconds: float = 30.0   # Discard prices older than this


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class ArbSignalStrength(str, Enum):
    NONE = "none"           # No meaningful divergence
    WEAK = "weak"           # Small gap — worth noting
    MODERATE = "moderate"   # Decent opportunity
    STRONG = "strong"       # Clear exploitable divergence


@dataclass
class VenueQuote:
    """A bid/ask snapshot from a single broker."""
    broker: str
    bid: float
    ask: float
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 0.0
        return (self.ask - self.bid) / self.mid * 100.0


@dataclass
class ArbSignal:
    """Arbitrage signal for a symbol across all tracked venues."""
    symbol: str
    strength: ArbSignalStrength
    spread_gap_pct: float           # Cross-broker spread gap as % of mid
    best_buy_venue: Optional[str]   # Cheapest ask → best for buys/longs
    best_sell_venue: Optional[str]  # Highest bid → best for sells/shorts
    best_buy_ask: float = 0.0
    best_sell_bid: float = 0.0
    venue_count: int = 0
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class CrossBrokerArbitrageMonitor:
    """
    Tracks cross-broker price divergences and suggests optimal venues.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self, config: Optional[ArbConfig] = None) -> None:
        self._config = config or ArbConfig()
        self._lock = threading.Lock()
        # { symbol: { broker: VenueQuote } }
        self._quotes: Dict[str, Dict[str, VenueQuote]] = {}
        logger.info("✅ CrossBrokerArbitrageMonitor initialised")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def update_price(
        self,
        broker: str,
        symbol: str,
        bid: float,
        ask: float,
    ) -> None:
        """Record a fresh bid/ask quote from *broker* for *symbol*."""
        if bid <= 0 or ask <= 0 or bid > ask:
            logger.debug(
                "CrossBrokerArb: ignoring invalid quote %s %s bid=%.6f ask=%.6f",
                broker, symbol, bid, ask,
            )
            return
        with self._lock:
            if symbol not in self._quotes:
                self._quotes[symbol] = {}
            self._quotes[symbol][broker] = VenueQuote(
                broker=broker, bid=bid, ask=ask
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_best_venue(self, symbol: str, side: str) -> Optional[str]:
        """
        Return the broker name offering the best fill for *side*.

        * ``side="buy"``  → broker with lowest ask price.
        * ``side="sell"`` → broker with highest bid price.

        Returns ``None`` when fewer than 2 fresh venues are available.
        """
        fresh = self._fresh_quotes(symbol)
        if len(fresh) < 1:
            return None
        if side.lower() in ("buy", "long"):
            return min(fresh, key=lambda q: q.ask).broker
        if side.lower() in ("sell", "short"):
            return max(fresh, key=lambda q: q.bid).broker
        return None

    def get_spread_gap(self, symbol: str) -> float:
        """
        Return the cross-broker spread gap as a percentage of mid-price.

        Gap = (max_bid − min_ask) / mid  — positive means overlap / arb.
        For normal markets with no overlap the value is negative or zero.
        We return the absolute gap between the best bid and best ask
        across all venues as a proxy for exploitable divergence.
        """
        fresh = self._fresh_quotes(symbol)
        if len(fresh) < 2:
            return 0.0
        max_bid = max(q.bid for q in fresh)
        min_ask = min(q.ask for q in fresh)
        mid = sum(q.mid for q in fresh) / len(fresh)
        if mid <= 0:
            return 0.0
        return (max_bid - min_ask) / mid * 100.0

    def get_arb_signal(self, symbol: str) -> ArbSignal:
        """Return a full ``ArbSignal`` for *symbol*."""
        fresh = self._fresh_quotes(symbol)
        gap = self.get_spread_gap(symbol)

        if len(fresh) < 2:
            return ArbSignal(
                symbol=symbol,
                strength=ArbSignalStrength.NONE,
                spread_gap_pct=gap,
                best_buy_venue=None,
                best_sell_venue=None,
                venue_count=len(fresh),
            )

        best_buy = min(fresh, key=lambda q: q.ask)
        best_sell = max(fresh, key=lambda q: q.bid)

        if gap >= self._config.strong_signal_pct:
            strength = ArbSignalStrength.STRONG
        elif gap >= (self._config.min_spread_gap_pct + self._config.strong_signal_pct) / 2:
            strength = ArbSignalStrength.MODERATE
        elif gap >= self._config.min_spread_gap_pct:
            strength = ArbSignalStrength.WEAK
        else:
            strength = ArbSignalStrength.NONE

        return ArbSignal(
            symbol=symbol,
            strength=strength,
            spread_gap_pct=gap,
            best_buy_venue=best_buy.broker,
            best_sell_venue=best_sell.broker,
            best_buy_ask=best_buy.ask,
            best_sell_bid=best_sell.bid,
            venue_count=len(fresh),
        )

    def get_report(self) -> Dict:
        """Return a summary dict suitable for dashboard/logging."""
        with self._lock:
            symbols = list(self._quotes.keys())

        report = {"symbols": {}}
        for sym in symbols:
            sig = self.get_arb_signal(sym)
            report["symbols"][sym] = {
                "strength": sig.strength.value,
                "spread_gap_pct": round(sig.spread_gap_pct, 4),
                "best_buy_venue": sig.best_buy_venue,
                "best_sell_venue": sig.best_sell_venue,
                "venue_count": sig.venue_count,
            }
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fresh_quotes(self, symbol: str) -> list:
        """Return only non-stale VenueQuote objects for *symbol*."""
        with self._lock:
            quotes = dict(self._quotes.get(symbol, {}))
        cutoff = time.monotonic() - self._config.stale_price_seconds
        return [q for q in quotes.values() if q.timestamp >= cutoff]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_monitor_instance: Optional[CrossBrokerArbitrageMonitor] = None
_monitor_lock = threading.Lock()


def get_arb_monitor(config: Optional[ArbConfig] = None) -> CrossBrokerArbitrageMonitor:
    """Return the singleton CrossBrokerArbitrageMonitor."""
    global _monitor_instance
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = CrossBrokerArbitrageMonitor(config=config)
    return _monitor_instance
