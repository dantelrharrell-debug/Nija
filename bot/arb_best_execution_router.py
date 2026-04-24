"""
NIJA Arb & Best-Execution Router
==================================

Combines **multi-broker arbitrage routing** with **best-execution selection**
into a single, lightweight decision layer that sits in front of every order.

Two capabilities in one module
-------------------------------
1. **Best-execution selection** — scores every connected broker for a given
   symbol/side using three dimensions:

   * ``price_score``   (60 % weight) — the effective net price after the
     per-broker fee, normalised across all live quotes.
   * ``fee_score``     (30 % weight) — cheaper fee → higher score.
   * ``latency_score`` (10 % weight) — drawn from ``BrokerPerformanceScorer``
     when available; falls back to a neutral 50/100.

   Returns the broker with the highest composite score so callers can pass
   ``preferred_broker`` to ``MultiBrokerExecutionRouter.route()``.

2. **Arbitrage routing** — detects when buying on broker A and selling on
   broker B yields a positive net profit after both sides' fees.  Emits an
   :class:`ArbRoute` that callers can execute via
   ``MultiBrokerExecutionRouter.route()`` twice (once per leg).

Architecture
------------
::

  ┌────────────────────────────────────────────────────────────────┐
  │               ArbBestExecutionRouter                           │
  │                                                                │
  │  update_price(broker, symbol, bid, ask)  ← feed each cycle    │
  │  score_brokers(symbol, side, size_usd)   → List[BrokerScore]  │
  │  get_best_broker(symbol, side)           → str | None         │
  │  find_arb_opportunity(symbol, size_usd)  → ArbRoute | None    │
  │  get_execution_recommendation(…)         → ExecRecommendation │
  │  get_report()                            → Dict               │
  └────────────────────────────────────────────────────────────────┘

Integrations
------------
* Reads live prices from :class:`~bot.cross_broker_arbitrage_monitor.CrossBrokerArbitrageMonitor`.
* Reads fee profiles from ``bot.broker_fee_optimizer.BROKER_FEE_PROFILES``.
* Reads latency/score data from :class:`~bot.broker_performance_scorer.BrokerPerformanceScorer`.
* Best-execution result wires into :meth:`MultiBrokerExecutionRouter.route`
  via the ``preferred_broker`` parameter.

Configuration via environment variables
----------------------------------------
``NIJA_ARB_MIN_PROFIT_PCT``      Minimum net profit to flag arb (default 0.10 %).
``NIJA_ARB_STALE_SECONDS``       Discard quotes older than this (default 30 s).
``NIJA_BEST_EXEC_PRICE_WEIGHT``  Weight for price score (default 0.60).
``NIJA_BEST_EXEC_FEE_WEIGHT``    Weight for fee score   (default 0.30).
``NIJA_BEST_EXEC_LAT_WEIGHT``    Weight for latency     (default 0.10).

Usage
-----
::

    from bot.arb_best_execution_router import get_arb_best_execution_router

    router = get_arb_best_execution_router()

    # Feed prices each cycle (after fetching from broker API):
    router.update_price("coinbase", "BTC-USD", bid=68_400.0, ask=68_420.0)
    router.update_price("kraken",   "BTC-USD", bid=68_380.0, ask=68_395.0)

    # Best broker for a BUY:
    best = router.get_best_broker("BTC-USD", side="buy")
    # → "kraken"  (cheaper ask + lower fees)

    # Full arbitrage + best-execution recommendation:
    rec = router.get_execution_recommendation("BTC-USD", side="buy", size_usd=500.0)
    print(rec.recommended_broker, rec.arb_opportunity)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.arb_best_exec")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Minimum net profit percentage to flag an arbitrage opportunity.
MIN_ARB_PROFIT_PCT: float = float(
    os.environ.get("NIJA_ARB_MIN_PROFIT_PCT", "0.10")
)

#: Discard quotes older than this many seconds.
STALE_QUOTE_SECONDS: float = float(
    os.environ.get("NIJA_ARB_STALE_SECONDS", "30")
)

# Composite score weights (must sum to 1.0).
_W_PRICE: float = float(os.environ.get("NIJA_BEST_EXEC_PRICE_WEIGHT", "0.60"))
_W_FEE: float   = float(os.environ.get("NIJA_BEST_EXEC_FEE_WEIGHT",   "0.30"))
_W_LAT: float   = float(os.environ.get("NIJA_BEST_EXEC_LAT_WEIGHT",   "0.10"))

# Fallback fee table when broker_fee_optimizer is unavailable.
# Values are *taker* fee fractions (e.g. 0.006 = 0.6 %).
_FALLBACK_FEES: Dict[str, float] = {
    "coinbase": 0.006,
    "kraken":   0.0026,
    "binance":  0.001,
    "okx":      0.001,
}
_DEFAULT_FEE: float = 0.003   # conservative default for unknown brokers


# ---------------------------------------------------------------------------
# Optional sub-system imports
# ---------------------------------------------------------------------------

try:
    from bot.cross_broker_arbitrage_monitor import get_arb_monitor as _get_arb_monitor
    _ARB_MONITOR_AVAILABLE = True
except ImportError:
    try:
        from cross_broker_arbitrage_monitor import get_arb_monitor as _get_arb_monitor
        _ARB_MONITOR_AVAILABLE = True
    except ImportError:
        _ARB_MONITOR_AVAILABLE = False
        _get_arb_monitor = None  # type: ignore

try:
    from bot.broker_fee_optimizer import BROKER_FEE_PROFILES as _FEE_PROFILES
    _FEE_PROFILES_AVAILABLE = True
except ImportError:
    try:
        from broker_fee_optimizer import BROKER_FEE_PROFILES as _FEE_PROFILES
        _FEE_PROFILES_AVAILABLE = True
    except ImportError:
        _FEE_PROFILES_AVAILABLE = False
        _FEE_PROFILES = {}  # type: ignore

try:
    from bot.broker_performance_scorer import get_broker_performance_scorer as _get_bps
    _BPS_AVAILABLE = True
except ImportError:
    try:
        from broker_performance_scorer import get_broker_performance_scorer as _get_bps
        _BPS_AVAILABLE = True
    except ImportError:
        _BPS_AVAILABLE = False
        _get_bps = None  # type: ignore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VenueSnapshot:
    """Live bid/ask from one broker for one symbol."""
    broker: str
    bid: float
    ask: float
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def is_fresh(self) -> bool:
        return (time.monotonic() - self.timestamp) < STALE_QUOTE_SECONDS


@dataclass
class BrokerScore:
    """Per-broker scoring result for a single symbol/side query."""
    broker: str
    side: str               # "buy" | "sell"
    raw_price: float        # ask (buy) or bid (sell)
    fee_pct: float          # taker fee fraction
    effective_price: float  # raw_price adjusted for fees
    price_score: float      # 0–100 (higher = better price)
    fee_score: float        # 0–100 (lower fee = higher score)
    latency_score: float    # 0–100
    net_score: float        # weighted composite 0–100


@dataclass
class ArbRoute:
    """
    A detected arbitrage opportunity: buy on ``buy_broker``, sell on
    ``sell_broker`` for the same ``symbol``.
    """
    symbol: str
    buy_broker: str
    sell_broker: str
    buy_ask: float          # price at which we buy
    sell_bid: float         # price at which we sell
    buy_fee_pct: float
    sell_fee_pct: float
    gross_spread_pct: float # (sell_bid - buy_ask) / buy_ask * 100
    total_fee_pct: float    # (buy_fee + sell_fee) * 100
    net_profit_pct: float   # gross - total_fees
    max_size_usd: float     # suggested trade notional
    is_executable: bool     # net_profit_pct >= MIN_ARB_PROFIT_PCT
    detected_at: float = field(default_factory=time.monotonic)

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.detected_at


@dataclass
class ExecutionRecommendation:
    """Combined best-execution + arb recommendation for one symbol/side."""
    symbol: str
    side: str
    recommended_broker: Optional[str]       # best single-broker execution
    broker_scores: List[BrokerScore]        # all scored brokers, descending
    arb_opportunity: Optional[ArbRoute]     # non-None if profitable arb exists
    reasoning: str                          # human-readable explanation


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ArbBestExecutionRouter:
    """
    Single-instance router that provides best-execution broker selection
    and cross-broker arbitrage detection.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # { symbol: { broker: VenueSnapshot } }
        self._snapshots: Dict[str, Dict[str, VenueSnapshot]] = {}
        # Lazy-initialised sub-system references
        self._arb_monitor = None
        self._bps = None
        # Counters for the report
        self._stats = {
            "price_updates": 0,
            "best_exec_queries": 0,
            "arb_detected": 0,
            "arb_executable": 0,
        }
        logger.info(
            "✅ ArbBestExecutionRouter initialised "
            "(min_arb=%.2f%%, stale=%.0fs, weights=price%.0f/fee%.0f/lat%.0f)",
            MIN_ARB_PROFIT_PCT,
            STALE_QUOTE_SECONDS,
            _W_PRICE * 100, _W_FEE * 100, _W_LAT * 100,
        )

    # ------------------------------------------------------------------
    # Price ingestion
    # ------------------------------------------------------------------

    def update_price(
        self,
        broker: str,
        symbol: str,
        bid: float,
        ask: float,
    ) -> None:
        """
        Record a fresh bid/ask quote from *broker* for *symbol*.

        Also forwards to the CrossBrokerArbitrageMonitor when available
        so both systems stay in sync from a single call site.

        Args:
            broker: Broker identifier, e.g. ``"coinbase"``.
            symbol: Trading symbol, e.g. ``"BTC-USD"``.
            bid: Best bid price.
            ask: Best ask price.
        """
        if bid <= 0 or ask <= 0 or bid > ask:
            return

        with self._lock:
            if symbol not in self._snapshots:
                self._snapshots[symbol] = {}
            self._snapshots[symbol][broker] = VenueSnapshot(
                broker=broker, bid=bid, ask=ask
            )
            self._stats["price_updates"] += 1

        # Forward to arb monitor for backward-compat with existing code
        arb_monitor = self._get_arb_monitor()
        if arb_monitor is not None:
            try:
                arb_monitor.update_price(broker, symbol, bid, ask)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Best-execution scoring
    # ------------------------------------------------------------------

    def score_brokers(
        self,
        symbol: str,
        side: str,
        size_usd: float = 100.0,
    ) -> List[BrokerScore]:
        """
        Score all brokers with fresh quotes for *symbol*/*side* and return
        them sorted from best (highest ``net_score``) to worst.

        Args:
            symbol: Trading pair, e.g. ``"ETH-USD"``.
            side: ``"buy"`` (want cheapest ask) or ``"sell"`` (want best bid).
            size_usd: Intended notional — reserved for future impact models.

        Returns:
            List of :class:`BrokerScore` sorted descending by ``net_score``.
            Empty list when no fresh quotes exist.
        """
        fresh = self._fresh_snapshots(symbol)
        if not fresh:
            return []

        side_lower = side.lower()
        is_buy = side_lower in ("buy", "long")

        # Raw prices per broker
        raw_prices = {
            s.broker: s.ask if is_buy else s.bid
            for s in fresh
        }

        # Fees per broker
        fees = {s.broker: self._get_fee(s.broker) for s in fresh}

        # Effective prices (inclusive of fee)
        effective = {
            broker: raw_prices[broker] * (1.0 + fees[broker]) if is_buy
                    else raw_prices[broker] * (1.0 - fees[broker])
            for broker in raw_prices
        }

        # Normalise prices → 0-100 (higher = better)
        prices_list = list(effective.values())
        p_min, p_max = min(prices_list), max(prices_list)
        p_range = p_max - p_min if p_max > p_min else 1.0

        if is_buy:
            # Cheaper effective ask = better
            price_scores = {
                b: (p_max - effective[b]) / p_range * 100.0
                for b in effective
            }
        else:
            # Higher effective bid = better
            price_scores = {
                b: (effective[b] - p_min) / p_range * 100.0
                for b in effective
            }

        # Normalise fees → 0-100 (lower fee = higher score)
        fees_list = list(fees.values())
        f_min, f_max = min(fees_list), max(fees_list)
        f_range = f_max - f_min if f_max > f_min else 1.0
        fee_scores = {
            b: (f_max - fees[b]) / f_range * 100.0
            for b in fees
        }

        # Latency scores from BrokerPerformanceScorer
        latency_scores = {b: self._get_latency_score(b) for b in raw_prices}

        # Composite
        results = []
        for broker in raw_prices:
            ps = price_scores[broker]
            fs = fee_scores[broker]
            ls = latency_scores[broker]
            net = ps * _W_PRICE + fs * _W_FEE + ls * _W_LAT
            results.append(BrokerScore(
                broker=broker,
                side=side,
                raw_price=raw_prices[broker],
                fee_pct=fees[broker],
                effective_price=effective[broker],
                price_score=round(ps, 2),
                fee_score=round(fs, 2),
                latency_score=round(ls, 2),
                net_score=round(net, 2),
            ))

        results.sort(key=lambda s: -s.net_score)

        with self._lock:
            self._stats["best_exec_queries"] += 1

        return results

    def get_best_broker(self, symbol: str, side: str) -> Optional[str]:
        """
        Return the name of the broker offering the best net execution for
        *symbol*/*side*, or ``None`` if no fresh quotes are available.

        Args:
            symbol: Trading pair.
            side: ``"buy"`` | ``"sell"``.

        Returns:
            Broker name string, or ``None``.
        """
        scores = self.score_brokers(symbol, side)
        if not scores:
            return None
        best = scores[0]
        logger.debug(
            "🎯 Best execution for %s %s → %s "
            "(net=%.1f, price=%.1f, fee=%.1f, lat=%.1f)",
            side.upper(), symbol, best.broker,
            best.net_score, best.price_score, best.fee_score, best.latency_score,
        )
        return best.broker

    # ------------------------------------------------------------------
    # Arbitrage detection
    # ------------------------------------------------------------------

    def find_arb_opportunity(
        self,
        symbol: str,
        size_usd: float = 100.0,
    ) -> Optional[ArbRoute]:
        """
        Detect a profitable arbitrage opportunity for *symbol* across all
        brokers with fresh quotes.

        An opportunity exists when::

            sell_bid_on_B > buy_ask_on_A × (1 + fee_A + fee_B)

        Only the pair yielding the highest ``net_profit_pct`` is returned.

        Args:
            symbol: Trading pair.
            size_usd: Suggested trade size for the :class:`ArbRoute`.

        Returns:
            :class:`ArbRoute` when profitable arb is found, else ``None``.
        """
        fresh = self._fresh_snapshots(symbol)
        if len(fresh) < 2:
            return None

        best_route: Optional[ArbRoute] = None

        for buy_snap in fresh:
            for sell_snap in fresh:
                if buy_snap.broker == sell_snap.broker:
                    continue

                buy_fee = self._get_fee(buy_snap.broker)
                sell_fee = self._get_fee(sell_snap.broker)
                total_fee = buy_fee + sell_fee

                # Gross spread: how much we make before fees
                gross = (sell_snap.bid - buy_snap.ask) / buy_snap.ask * 100.0
                net = gross - total_fee * 100.0

                if net <= 0:
                    continue

                route = ArbRoute(
                    symbol=symbol,
                    buy_broker=buy_snap.broker,
                    sell_broker=sell_snap.broker,
                    buy_ask=buy_snap.ask,
                    sell_bid=sell_snap.bid,
                    buy_fee_pct=buy_fee,
                    sell_fee_pct=sell_fee,
                    gross_spread_pct=round(gross, 4),
                    total_fee_pct=round(total_fee * 100.0, 4),
                    net_profit_pct=round(net, 4),
                    max_size_usd=size_usd,
                    is_executable=net >= MIN_ARB_PROFIT_PCT,
                )

                if best_route is None or route.net_profit_pct > best_route.net_profit_pct:
                    best_route = route

        if best_route is not None:
            with self._lock:
                self._stats["arb_detected"] += 1
                if best_route.is_executable:
                    self._stats["arb_executable"] += 1

            if best_route.is_executable:
                logger.info(
                    "⚡ ARB OPPORTUNITY %s: buy@%s (%.4f) sell@%s (%.4f) "
                    "net=+%.3f%% size=$%.0f",
                    symbol,
                    best_route.buy_broker, best_route.buy_ask,
                    best_route.sell_broker, best_route.sell_bid,
                    best_route.net_profit_pct, size_usd,
                )
            else:
                logger.debug(
                    "   Arb detected but below threshold (%.3f%% < %.2f%%) for %s",
                    best_route.net_profit_pct, MIN_ARB_PROFIT_PCT, symbol,
                )

        return best_route if (best_route and best_route.is_executable) else None

    # ------------------------------------------------------------------
    # Combined recommendation
    # ------------------------------------------------------------------

    def get_execution_recommendation(
        self,
        symbol: str,
        side: str,
        size_usd: float = 100.0,
    ) -> ExecutionRecommendation:
        """
        Return a complete :class:`ExecutionRecommendation` combining:

        * The best-execution broker for the requested *side*.
        * Any live executable arbitrage opportunity.

        When an arb opportunity is present and *side* is ``"buy"``, the
        recommendation will indicate the arb's ``buy_broker`` as the
        ``recommended_broker``.

        Args:
            symbol: Trading pair.
            side: ``"buy"`` | ``"sell"``.
            size_usd: Intended notional.

        Returns:
            :class:`ExecutionRecommendation`.
        """
        scores = self.score_brokers(symbol, side, size_usd)
        arb = self.find_arb_opportunity(symbol, size_usd)

        recommended = scores[0].broker if scores else None
        reasoning_parts = []

        if arb:
            # Override recommended broker with arb-optimal side
            if side.lower() in ("buy", "long"):
                recommended = arb.buy_broker
                reasoning_parts.append(
                    f"ARB: buy@{arb.buy_broker} net+{arb.net_profit_pct:.3f}%"
                )
            else:
                recommended = arb.sell_broker
                reasoning_parts.append(
                    f"ARB: sell@{arb.sell_broker} net+{arb.net_profit_pct:.3f}%"
                )
        elif scores:
            top = scores[0]
            reasoning_parts.append(
                f"BestExec: {top.broker} score={top.net_score:.1f} "
                f"(price={top.price_score:.1f}, fee={top.fee_score:.1f}, "
                f"lat={top.latency_score:.1f})"
            )

        if not reasoning_parts:
            reasoning_parts.append("no fresh quotes — routing unchanged")

        return ExecutionRecommendation(
            symbol=symbol,
            side=side,
            recommended_broker=recommended,
            broker_scores=scores,
            arb_opportunity=arb,
            reasoning="; ".join(reasoning_parts),
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict:
        """Return a serialisable status snapshot."""
        with self._lock:
            stats = dict(self._stats)
            symbols = list(self._snapshots.keys())

        report: Dict = {"stats": stats, "symbols": {}}
        for sym in symbols:
            fresh = self._fresh_snapshots(sym)
            report["symbols"][sym] = {
                "venue_count": len(fresh),
                "venues": {
                    s.broker: {
                        "bid": s.bid,
                        "ask": s.ask,
                        "age_s": round(time.monotonic() - s.timestamp, 1),
                    }
                    for s in fresh
                },
            }
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fresh_snapshots(self, symbol: str) -> List[VenueSnapshot]:
        """Return fresh (non-stale) VenueSnapshot objects for *symbol*."""
        with self._lock:
            snaps = dict(self._snapshots.get(symbol, {}))
        return [s for s in snaps.values() if s.is_fresh]

    def _get_fee(self, broker: str) -> float:
        """Return the taker fee fraction for *broker*."""
        broker_lower = broker.lower()
        if _FEE_PROFILES_AVAILABLE and broker_lower in _FEE_PROFILES:
            return _FEE_PROFILES[broker_lower].taker_fee_pct
        return _FALLBACK_FEES.get(broker_lower, _DEFAULT_FEE)

    def _get_latency_score(self, broker: str) -> float:
        """
        Return a 0-100 latency score for *broker* from BrokerPerformanceScorer.
        Falls back to 50.0 (neutral) when the scorer is unavailable.
        """
        bps = self._get_bps()
        if bps is None:
            return 50.0
        try:
            raw = bps.get_score(broker)
            # BPS scores are typically 0-100; clamp and return as-is
            return float(max(0.0, min(100.0, raw)))
        except Exception:
            return 50.0

    def _get_arb_monitor(self):
        if self._arb_monitor is None and _ARB_MONITOR_AVAILABLE and _get_arb_monitor:
            try:
                self._arb_monitor = _get_arb_monitor()
            except Exception:
                pass
        return self._arb_monitor

    def _get_bps(self):
        if self._bps is None and _BPS_AVAILABLE and _get_bps:
            try:
                self._bps = _get_bps()
            except Exception:
                pass
        return self._bps


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_router_instance: Optional[ArbBestExecutionRouter] = None
_router_lock = threading.Lock()


def get_arb_best_execution_router() -> ArbBestExecutionRouter:
    """
    Return (or create) the process-wide :class:`ArbBestExecutionRouter`
    singleton.

    Returns:
        :class:`ArbBestExecutionRouter` instance.
    """
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = ArbBestExecutionRouter()
    return _router_instance


def reset_arb_best_execution_router() -> None:
    """Destroy the singleton (primarily for testing)."""
    global _router_instance
    with _router_lock:
        _router_instance = None
