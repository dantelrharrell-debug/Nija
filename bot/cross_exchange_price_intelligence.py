"""
Cross-Exchange Price Intelligence
===================================
Tracks asset prices across multiple exchanges, detects divergences, and
surfaces arbitrage-quality signals for smarter entry timing.

Features
--------
  * Multi-venue price registry with staleness TTL
  * Bid/ask spread normalization across venues
  * Divergence detection: Z-score of price vs. cross-exchange mean
  * Arbitrage opportunity scoring (0-100) with direction annotation
  * Per-symbol price consensus (volume-weighted mid)
  * Alert escalation: INFO / WARNING / CRITICAL divergences
  * Portfolio-level divergence heatmap

Public API
----------
  intel = get_cross_exchange_price_intelligence()
  intel.update_price(exchange, symbol, bid, ask, volume_usd)
  result = intel.get_divergence(symbol)
  ok     = intel.approve_entry(symbol, max_divergence_pct=0.5)
  report = intel.get_portfolio_divergence_report()
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.cross_exchange_price_intelligence")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Price tick older than this (seconds) is considered stale
PRICE_STALENESS_TTL: float = 30.0

# Z-score thresholds for divergence severity
DIVERGENCE_Z_INFO     = 1.5
DIVERGENCE_Z_WARNING  = 2.5
DIVERGENCE_Z_CRITICAL = 4.0

# Rolling history (bars) for Z-score baseline
DIVERGENCE_HISTORY_LEN = 100

# Minimum number of exchanges required to compute a meaningful divergence
MIN_EXCHANGES_FOR_DIVERGENCE = 2

# Known exchange priority weights (higher weight = more trusted/liquid venue)
_VENUE_TRUST: Dict[str, float] = {
    "coinbase":  1.0,
    "binance":   1.0,
    "kraken":    0.9,
    "bybit":     0.85,
    "okx":       0.85,
    "bitfinex":  0.80,
    "gemini":    0.80,
    "huobi":     0.75,
    "kucoin":    0.70,
}
_DEFAULT_TRUST = 0.65


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class PriceTick:
    """A single price observation from one exchange."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    volume_usd: float
    mid: float = field(init=False)
    spread_pct: float = field(init=False)
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def __post_init__(self) -> None:
        self.mid = (self.bid + self.ask) / 2.0 if self.bid > 0 and self.ask > 0 else 0.0
        self.spread_pct = (
            (self.ask - self.bid) / self.mid if self.mid > 0 else 0.0
        )

    @property
    def is_stale(self) -> bool:
        age = datetime.now(timezone.utc).timestamp() - self.timestamp
        return age > PRICE_STALENESS_TTL


@dataclass
class DivergenceResult:
    """Divergence analysis for a single symbol across all tracked exchanges."""
    symbol: str
    exchange_count: int
    consensus_price: float           # volume-weighted mid across venues
    min_price: float
    max_price: float
    spread_pct: float                # (max-min)/consensus as a fraction
    z_score: float                   # vs. rolling history
    divergence_pct: float            # max deviation from consensus (%)
    severity: str                    # NORMAL | INFO | WARNING | CRITICAL
    arb_score: float                 # 0-100 arbitrage opportunity score
    arb_direction: str               # "BUY_LOW_SELL_HIGH" | "NEUTRAL"
    cheapest_venue: str
    most_expensive_venue: str
    venues: List[Dict[str, Any]]
    approved: bool                   # True if divergence within acceptable range
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange_count": self.exchange_count,
            "consensus_price": round(self.consensus_price, 8),
            "min_price": round(self.min_price, 8),
            "max_price": round(self.max_price, 8),
            "spread_pct": round(self.spread_pct * 100, 4),
            "z_score": round(self.z_score, 3),
            "divergence_pct": round(self.divergence_pct, 4),
            "severity": self.severity,
            "arb_score": round(self.arb_score, 2),
            "arb_direction": self.arb_direction,
            "cheapest_venue": self.cheapest_venue,
            "most_expensive_venue": self.most_expensive_venue,
            "venues": self.venues,
            "approved": self.approved,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class PortfolioDivergenceReport:
    """Aggregate divergence health across all tracked symbols."""
    symbol_count: int
    avg_divergence_pct: float
    max_divergence_pct: float
    pct_normal: float
    pct_info: float
    pct_warning: float
    pct_critical: float
    critical_symbols: List[str]
    top_arb_opportunities: List[Dict[str, Any]]
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_count": self.symbol_count,
            "avg_divergence_pct": round(self.avg_divergence_pct, 4),
            "max_divergence_pct": round(self.max_divergence_pct, 4),
            "pct_normal": round(self.pct_normal, 2),
            "pct_info": round(self.pct_info, 2),
            "pct_warning": round(self.pct_warning, 2),
            "pct_critical": round(self.pct_critical, 2),
            "critical_symbols": self.critical_symbols,
            "top_arb_opportunities": self.top_arb_opportunities,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

class CrossExchangePriceIntelligence:
    """
    Multi-venue price tracker with divergence detection and arbitrage scoring.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        staleness_ttl: float = PRICE_STALENESS_TTL,
        divergence_history_len: int = DIVERGENCE_HISTORY_LEN,
    ) -> None:
        self._ttl         = max(1.0, staleness_ttl)
        self._hist_len    = max(10, divergence_history_len)
        self._lock        = threading.RLock()

        # Latest tick per (exchange, symbol)
        self._ticks: Dict[Tuple[str, str], PriceTick] = {}
        # Rolling history of cross-exchange divergence pct per symbol
        self._div_history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self._hist_len)
        )
        # Cache of latest divergence results
        self._divergence_cache: Dict[str, DivergenceResult] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_price(
        self,
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
        volume_usd: float = 0.0,
    ) -> None:
        """
        Ingest a new price tick from *exchange* for *symbol*.

        Parameters
        ----------
        exchange   : Normalised exchange name (e.g. "coinbase", "binance").
        symbol     : Trading pair (e.g. "BTC-USD").
        bid        : Best bid price.
        ask        : Best ask price.
        volume_usd : Recent traded volume in USD (used for weighting).
        """
        if bid <= 0 or ask <= 0 or ask < bid:
            logger.debug(
                "[CrossExchange] Invalid tick ignored: %s@%s bid=%.8f ask=%.8f",
                symbol, exchange, bid, ask,
            )
            return

        tick = PriceTick(
            exchange=exchange.lower(),
            symbol=symbol,
            bid=bid,
            ask=ask,
            volume_usd=max(0.0, volume_usd),
        )
        with self._lock:
            self._ticks[(exchange.lower(), symbol)] = tick
            # Invalidate cached divergence result
            self._divergence_cache.pop(symbol, None)

    def get_divergence(self, symbol: str) -> Optional[DivergenceResult]:
        """
        Compute and return the current price divergence across all venues
        tracking *symbol*.  Returns None when fewer than
        MIN_EXCHANGES_FOR_DIVERGENCE venues have fresh data.
        """
        with self._lock:
            if symbol in self._divergence_cache:
                return self._divergence_cache[symbol]

            result = self._compute_divergence(symbol)
            if result is not None:
                self._divergence_cache[symbol] = result
            return result

    def approve_entry(
        self,
        symbol: str,
        max_divergence_pct: float = 0.5,
    ) -> bool:
        """
        Return True if cross-exchange divergence for *symbol* is within
        *max_divergence_pct* percent.  Returns True when insufficient
        exchange data is available (benefit of the doubt).

        Parameters
        ----------
        max_divergence_pct : Maximum acceptable divergence in percent (default 0.5%).
        """
        result = self.get_divergence(symbol)
        if result is None:
            return True  # not enough data → do not block
        return result.divergence_pct <= max_divergence_pct

    def get_consensus_price(self, symbol: str) -> Optional[float]:
        """Return volume-weighted consensus mid-price across live venues, or None."""
        result = self.get_divergence(symbol)
        return result.consensus_price if result else None

    def get_portfolio_divergence_report(self) -> PortfolioDivergenceReport:
        """Aggregate divergence health across all tracked symbols."""
        with self._lock:
            symbols = {sym for (_, sym) in self._ticks.keys()}

        results: List[DivergenceResult] = []
        for sym in symbols:
            r = self.get_divergence(sym)
            if r is not None:
                results.append(r)

        if not results:
            return PortfolioDivergenceReport(
                symbol_count=0,
                avg_divergence_pct=0.0,
                max_divergence_pct=0.0,
                pct_normal=100.0,
                pct_info=0.0,
                pct_warning=0.0,
                pct_critical=0.0,
                critical_symbols=[],
                top_arb_opportunities=[],
            )

        n = len(results)
        severity_counts: Dict[str, int] = defaultdict(int)
        for r in results:
            severity_counts[r.severity] += 1

        divs = [r.divergence_pct for r in results]
        top_arb = sorted(results, key=lambda r: r.arb_score, reverse=True)[:5]

        return PortfolioDivergenceReport(
            symbol_count=n,
            avg_divergence_pct=float(np.mean(divs)),
            max_divergence_pct=float(np.max(divs)),
            pct_normal=100.0   * severity_counts["NORMAL"]   / n,
            pct_info=100.0     * severity_counts["INFO"]     / n,
            pct_warning=100.0  * severity_counts["WARNING"]  / n,
            pct_critical=100.0 * severity_counts["CRITICAL"] / n,
            critical_symbols=[r.symbol for r in results if r.severity == "CRITICAL"],
            top_arb_opportunities=[
                {"symbol": r.symbol, "arb_score": round(r.arb_score, 2),
                 "divergence_pct": round(r.divergence_pct, 4),
                 "buy_at": r.cheapest_venue, "sell_at": r.most_expensive_venue}
                for r in top_arb if r.arb_score > 0
            ],
        )

    def list_tracked_symbols(self) -> List[str]:
        """Return a sorted list of all symbols with at least one live tick."""
        with self._lock:
            return sorted({sym for (_, sym) in self._ticks.keys()})

    def purge_stale_ticks(self) -> int:
        """Remove ticks older than the staleness TTL. Returns count removed."""
        with self._lock:
            stale = [k for k, v in self._ticks.items() if v.is_stale]
            for k in stale:
                del self._ticks[k]
            return len(stale)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_divergence(self, symbol: str) -> Optional[DivergenceResult]:
        """(Must be called with self._lock held.)"""
        # Collect fresh ticks for symbol across all exchanges
        fresh: List[PriceTick] = [
            tick for (_, sym), tick in self._ticks.items()
            if sym == symbol and not tick.is_stale
        ]

        if len(fresh) < MIN_EXCHANGES_FOR_DIVERGENCE:
            return None

        # Volume-weighted consensus mid
        total_vol = sum(t.volume_usd for t in fresh)
        if total_vol > 0:
            consensus = sum(t.mid * t.volume_usd for t in fresh) / total_vol
        else:
            consensus = float(np.mean([t.mid for t in fresh]))

        if consensus <= 0:
            return None

        mids = [t.mid for t in fresh]
        min_price = min(mids)
        max_price = max(mids)
        spread_pct = (max_price - min_price) / consensus

        # Max deviation from consensus (%)
        divergence_pct = max(abs(t.mid - consensus) / consensus * 100.0 for t in fresh)

        # Compute Z-score against existing history *before* appending the
        # current observation, so the baseline statistics are not contaminated
        # by the value being scored.
        hist = self._div_history[symbol]
        z_score = self._compute_z_score(divergence_pct, hist)
        hist.append(divergence_pct)

        severity = self._z_to_severity(z_score)
        arb_score, arb_direction = self._compute_arb_score(spread_pct, fresh)

        cheapest = min(fresh, key=lambda t: t.mid)
        most_expensive = max(fresh, key=lambda t: t.mid)

        approved = severity in ("NORMAL", "INFO")
        reason = self._build_reason(severity, divergence_pct, z_score, len(fresh))

        venues = [
            {
                "exchange": t.exchange,
                "mid": round(t.mid, 8),
                "bid": round(t.bid, 8),
                "ask": round(t.ask, 8),
                "spread_pct": round(t.spread_pct * 100, 4),
                "volume_usd": round(t.volume_usd, 2),
                "deviation_pct": round(abs(t.mid - consensus) / consensus * 100, 4),
            }
            for t in sorted(fresh, key=lambda t: t.exchange)
        ]

        return DivergenceResult(
            symbol=symbol,
            exchange_count=len(fresh),
            consensus_price=consensus,
            min_price=min_price,
            max_price=max_price,
            spread_pct=spread_pct,
            z_score=z_score,
            divergence_pct=divergence_pct,
            severity=severity,
            arb_score=arb_score,
            arb_direction=arb_direction,
            cheapest_venue=cheapest.exchange,
            most_expensive_venue=most_expensive.exchange,
            venues=venues,
            approved=approved,
            reason=reason,
        )

    @staticmethod
    def _compute_z_score(value: float, history: Deque[float]) -> float:
        if len(history) < 5:
            return 0.0
        arr = np.array(list(history), dtype=float)
        mu    = float(np.mean(arr))
        sigma = float(np.std(arr))
        if sigma < 1e-10:
            return 0.0
        return (value - mu) / sigma

    @staticmethod
    def _z_to_severity(z: float) -> str:
        az = abs(z)
        if az >= DIVERGENCE_Z_CRITICAL:
            return "CRITICAL"
        if az >= DIVERGENCE_Z_WARNING:
            return "WARNING"
        if az >= DIVERGENCE_Z_INFO:
            return "INFO"
        return "NORMAL"

    @staticmethod
    def _compute_arb_score(
        spread_pct: float,
        ticks: List[PriceTick],
    ) -> Tuple[float, str]:
        """
        Map cross-exchange spread to an arbitrage opportunity score (0-100).
        Higher score means larger potential profit net of fees.
        Rough fee assumption: 0.15% round-trip.
        """
        fee_roundtrip = 0.0015  # 0.15%
        net_spread = spread_pct - fee_roundtrip
        if net_spread <= 0:
            return 0.0, "NEUTRAL"

        # Score: sigmoid-like mapping [0, 2%] → [0, 100]
        score = min(100.0, net_spread / 0.02 * 100.0)

        # Determine direction (buy cheapest, sell most expensive)
        cheapest = min(ticks, key=lambda t: t.mid)
        most_exp = max(ticks, key=lambda t: t.mid)
        direction = f"BUY_{cheapest.exchange.upper()}_SELL_{most_exp.exchange.upper()}"

        return round(score, 2), direction

    @staticmethod
    def _build_reason(
        severity: str,
        divergence_pct: float,
        z_score: float,
        n_exchanges: int,
    ) -> str:
        flag = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵", "NORMAL": "🟢"}.get(severity, "")
        return (
            f"{flag} severity={severity} | "
            f"divergence={divergence_pct:.4f}% | "
            f"z={z_score:.2f} | "
            f"exchanges={n_exchanges}"
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_intel_instance: Optional[CrossExchangePriceIntelligence] = None
_intel_lock = threading.Lock()


def get_cross_exchange_price_intelligence(
    staleness_ttl: float = PRICE_STALENESS_TTL,
    divergence_history_len: int = DIVERGENCE_HISTORY_LEN,
) -> CrossExchangePriceIntelligence:
    """
    Return the process-wide CrossExchangePriceIntelligence singleton.

    Constructor arguments are applied only on first creation.
    """
    global _intel_instance
    with _intel_lock:
        if _intel_instance is None:
            _intel_instance = CrossExchangePriceIntelligence(
                staleness_ttl=staleness_ttl,
                divergence_history_len=divergence_history_len,
            )
            logger.info(
                "✅ CrossExchangePriceIntelligence initialised "
                "(ttl=%.0fs, history=%d bars)",
                staleness_ttl,
                divergence_history_len,
            )
    return _intel_instance
