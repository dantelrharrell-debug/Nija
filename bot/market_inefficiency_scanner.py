"""
NIJA Market Inefficiency Scanner (MIS)
========================================

The MIS is an **alpha generator** that sits above all NIJA strategies.
It detects short-lived pricing dislocations, statistical anomalies, and
microstructure inefficiencies — then converts them into structured signals
consumed by the Global Portfolio Engine and Execution Router.

Detection Pillars
-----------------
1. **Cross-Venue Spread Arbitrage** — price divergence across exchanges
   (integrates with CrossExchangePriceIntelligence).
2. **Funding Rate Arbitrage** — futures vs. spot mispricing.
3. **Microstructure Shock** — sudden bid/ask spread widening or collapse.
4. **Volume Surge Anomaly** — Z-score spike in rolling volume baseline.
5. **Latency Arbitrage** — sub-second price lag between slow and fast venues.
6. **ML Inefficiency Model** — lightweight online-learning model that scores
   each symbol's likelihood of short-term mean reversion.

Public API
----------
::

    from bot.market_inefficiency_scanner import get_market_inefficiency_scanner

    mis = get_market_inefficiency_scanner()

    # Feed live market ticks before scanning:
    mis.update_tick(exchange="coinbase", symbol="BTC-USD",
                    bid=67_000.0, ask=67_010.0, volume_usd=5e6,
                    funding_rate=0.0003)

    # Scan a list of symbols and return actionable signals:
    signals = mis.scan(["BTC-USD", "ETH-USD", "XRP-USD"])

    for signal in signals:
        decision = global_portfolio_engine.request_entry(
            strategy="MIS",
            symbol=signal.symbol,
            side=signal.action,
            size_usd=signal.expected_profit_usd,
            portfolio_value_usd=portfolio_value,
        )
        if decision.approved:
            execution_router.execute(OrderRequest(
                strategy="MIS",
                symbol=signal.symbol,
                side=signal.action,
                size_usd=signal.expected_profit_usd,
            ))

    # Full dashboard report:
    report = mis.get_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.market_inefficiency_scanner")

# ---------------------------------------------------------------------------
# Optional integrations — each degrades gracefully if unavailable.
# ---------------------------------------------------------------------------

try:
    from cross_exchange_price_intelligence import get_cross_exchange_price_intelligence
    _CEPI_AVAILABLE = True
except ImportError:
    try:
        from bot.cross_exchange_price_intelligence import get_cross_exchange_price_intelligence
        _CEPI_AVAILABLE = True
    except ImportError:
        _CEPI_AVAILABLE = False
        get_cross_exchange_price_intelligence = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum signal confidence to include in scan output
MIN_CONFIDENCE: float = 0.55

# Rolling window length for baseline statistics (bars / ticks)
BASELINE_WINDOW: int = 120

# Volume Z-score threshold to trigger a volume-surge signal
VOLUME_Z_THRESHOLD: float = 2.5

# Spread Z-score threshold to trigger a microstructure-shock signal
SPREAD_Z_THRESHOLD: float = 2.5

# Latency arbitrage: if one venue is this many milliseconds slower, flag it
LATENCY_ARBITRAGE_MS: float = 200.0

# Funding rate (annualised) beyond which we flag a funding-rate arb
FUNDING_RATE_ANNUALISED_THRESHOLD: float = 0.20   # 20% p.a.

# Minimum cross-venue spread (bps) to generate a cross-venue signal
CROSS_VENUE_SPREAD_MIN_BPS: float = 10.0

# ML model: EWM alpha for online scoring update
ML_EWM_ALPHA: float = 0.1

# Number of recent signals to retain for reporting
SIGNAL_HISTORY_LEN: int = 500

# Seconds between automatic scan resets (clears stale tick data)
STALE_TICK_TTL: float = 60.0


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class InefficiciencyType(str, Enum):
    CROSS_VENUE_SPREAD   = "cross_venue_spread"
    FUNDING_RATE_ARB     = "funding_rate_arb"
    MICROSTRUCTURE_SHOCK = "microstructure_shock"
    VOLUME_SURGE         = "volume_surge"
    LATENCY_ARBITRAGE    = "latency_arbitrage"
    ML_REVERSION         = "ml_reversion"


class SignalAction(str, Enum):
    BUY  = "buy"
    SELL = "sell"
    HOLD = "hold"


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class MarketTick:
    """A single live price/volume observation for one symbol from one venue."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    volume_usd: float
    funding_rate: float = 0.0          # perpetual funding rate (e.g. 0.0001 per 8 h)
    latency_ms: float = 0.0            # round-trip latency to this venue
    timestamp: float = field(default_factory=lambda: time.time())

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0 if self.bid > 0 and self.ask > 0 else 0.0

    @property
    def spread_bps(self) -> float:
        return (self.ask - self.bid) / self.mid * 10_000 if self.mid > 0 else 0.0

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.timestamp) > STALE_TICK_TTL


@dataclass
class InefficiciencySignal:
    """Structured output signal produced by the MIS scan."""
    signal_id: str
    symbol: str
    inefficiency_type: InefficiciencyType
    action: str                        # "buy" | "sell" | "hold"
    confidence: float                  # 0.0 – 1.0
    expected_profit_usd: float         # estimated gross USD profit
    expected_profit_bps: float         # in basis points (cleaner for small positions)
    description: str
    source_exchanges: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "inefficiency_type": self.inefficiency_type.value,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "expected_profit_usd": round(self.expected_profit_usd, 4),
            "expected_profit_bps": round(self.expected_profit_bps, 4),
            "description": self.description,
            "source_exchanges": self.source_exchanges,
            "extra": self.extra,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Per-Symbol Baseline Tracker
# ---------------------------------------------------------------------------

class _SymbolBaseline:
    """Maintains rolling statistics for a single symbol across all venues."""

    def __init__(self, window: int = BASELINE_WINDOW) -> None:
        self._window = window
        self.volume_history: Deque[float] = deque(maxlen=window)
        self.spread_history: Deque[float] = deque(maxlen=window)
        self.mid_history: Deque[float] = deque(maxlen=window)
        self.ticks: Dict[str, MarketTick] = {}  # exchange → latest tick
        # ML model: EWM score [-1, +1] (negative = oversold / reversion up)
        self.ml_score: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def ingest(self, tick: MarketTick) -> None:
        with self._lock:
            self.ticks[tick.exchange] = tick
            self.volume_history.append(tick.volume_usd)
            self.spread_history.append(tick.spread_bps)
            self.mid_history.append(tick.mid)
            self._update_ml(tick)

    def _update_ml(self, tick: MarketTick) -> None:
        """Update online EWM ML score based on spread & volume z-scores."""
        if len(self.spread_history) < 10:
            return
        arr = np.asarray(self.spread_history)
        mu, sigma = arr.mean(), arr.std(ddof=1) + 1e-9
        z_spread = (tick.spread_bps - mu) / sigma
        # Wide spread → price will mean-revert → score toward buy
        target = -math.tanh(z_spread / 3.0)
        self.ml_score = (1 - ML_EWM_ALPHA) * self.ml_score + ML_EWM_ALPHA * target

    # ------------------------------------------------------------------
    def volume_z(self) -> float:
        if len(self.volume_history) < 10:
            return 0.0
        arr = np.asarray(self.volume_history)
        mu, sigma = arr.mean(), arr.std(ddof=1) + 1e-9
        return float((arr[-1] - mu) / sigma)

    def spread_z(self) -> float:
        if len(self.spread_history) < 10:
            return 0.0
        arr = np.asarray(self.spread_history)
        mu, sigma = arr.mean(), arr.std(ddof=1) + 1e-9
        return float((arr[-1] - mu) / sigma)

    def fresh_ticks(self) -> List[MarketTick]:
        return [t for t in self.ticks.values() if not t.is_stale]

    def cross_venue_spread_bps(self) -> Tuple[Optional[str], Optional[str], float]:
        """Return (cheap_exchange, expensive_exchange, spread_bps) or (None, None, 0)."""
        fresh = self.fresh_ticks()
        if len(fresh) < 2:
            return None, None, 0.0
        bids = [(t.exchange, t.bid) for t in fresh]
        asks = [(t.exchange, t.ask) for t in fresh]
        cheap_ex, best_ask = min(asks, key=lambda x: x[1])
        exp_ex, best_bid = max(bids, key=lambda x: x[1])
        if cheap_ex == exp_ex or best_ask <= 0:
            return None, None, 0.0
        spread = (best_bid - best_ask) / best_ask * 10_000
        return cheap_ex, exp_ex, max(spread, 0.0)


# ---------------------------------------------------------------------------
# Market Inefficiency Scanner
# ---------------------------------------------------------------------------

class MarketInefficiciencyScanner:
    """
    Scans a list of symbols for short-lived market inefficiencies and
    returns structured :class:`InefficiciencySignal` objects.

    Usage
    -----
    ::

        mis = get_market_inefficiency_scanner()

        # Feed ticks (call this per exchange per tick)
        mis.update_tick(exchange="coinbase", symbol="BTC-USD",
                        bid=67000, ask=67010, volume_usd=5e6)

        # Scan and get signals
        signals = mis.scan(["BTC-USD", "ETH-USD"])

    """

    def __init__(self) -> None:
        self._baselines: Dict[str, _SymbolBaseline] = defaultdict(_SymbolBaseline)
        self._signal_history: Deque[InefficiciencySignal] = deque(
            maxlen=SIGNAL_HISTORY_LEN
        )
        self._signal_counter: int = 0
        self._lock = threading.Lock()
        self._stats: Dict[str, int] = defaultdict(int)
        logger.info("🔬 MarketInefficiciencyScanner initialised.")

    # ------------------------------------------------------------------
    # Public: data ingestion
    # ------------------------------------------------------------------

    def update_tick(
        self,
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
        volume_usd: float,
        funding_rate: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """
        Ingest a live market tick.  Call this once per exchange per bar or
        WebSocket update before calling :meth:`scan`.
        """
        tick = MarketTick(
            exchange=exchange,
            symbol=symbol,
            bid=bid,
            ask=ask,
            volume_usd=volume_usd,
            funding_rate=funding_rate,
            latency_ms=latency_ms,
        )
        self._baselines[symbol].ingest(tick)

    # ------------------------------------------------------------------
    # Public: scan
    # ------------------------------------------------------------------

    def scan(self, symbols: List[str]) -> List[InefficiciencySignal]:
        """
        Scan the provided symbols for market inefficiencies.

        Returns a list of :class:`InefficiciencySignal` objects sorted by
        descending confidence.  Only signals with confidence >= MIN_CONFIDENCE
        are included.
        """
        signals: List[InefficiciencySignal] = []

        for symbol in symbols:
            baseline = self._baselines.get(symbol)
            if baseline is None or not baseline.fresh_ticks():
                continue

            signals.extend(self._detect_cross_venue_spread(symbol, baseline))
            signals.extend(self._detect_funding_rate_arb(symbol, baseline))
            signals.extend(self._detect_microstructure_shock(symbol, baseline))
            signals.extend(self._detect_volume_surge(symbol, baseline))
            signals.extend(self._detect_latency_arbitrage(symbol, baseline))
            signals.extend(self._detect_ml_reversion(symbol, baseline))

        # Filter and sort
        signals = [s for s in signals if s.confidence >= MIN_CONFIDENCE]
        signals.sort(key=lambda s: s.confidence, reverse=True)

        for signal in signals:
            self._signal_history.append(signal)
            self._stats[signal.inefficiency_type.value] += 1

        if signals:
            logger.info(
                "🎯 MIS scan: %d signal(s) across %d symbol(s)",
                len(signals), len(symbols),
            )

        return signals

    # ------------------------------------------------------------------
    # Detection pillar 1: Cross-venue spread arbitrage
    # ------------------------------------------------------------------

    def _detect_cross_venue_spread(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        cheap_ex, exp_ex, spread_bps = bl.cross_venue_spread_bps()
        if cheap_ex is None or spread_bps < CROSS_VENUE_SPREAD_MIN_BPS:
            return []

        # Confidence scales with spread magnitude
        confidence = min(0.99, 0.55 + (spread_bps - CROSS_VENUE_SPREAD_MIN_BPS) / 100.0)
        # Rough profit estimate: 1 000 USD position
        profit_usd = 1_000.0 * spread_bps / 10_000.0

        return [self._make_signal(
            symbol=symbol,
            itype=InefficiciencyType.CROSS_VENUE_SPREAD,
            action=SignalAction.BUY.value,
            confidence=confidence,
            profit_usd=profit_usd,
            profit_bps=spread_bps,
            description=(
                f"Cross-venue spread of {spread_bps:.1f} bps: "
                f"buy on {cheap_ex}, sell on {exp_ex}"
            ),
            exchanges=[cheap_ex, exp_ex],
            extra={"spread_bps": spread_bps, "buy_venue": cheap_ex, "sell_venue": exp_ex},
        )]

    # ------------------------------------------------------------------
    # Detection pillar 2: Funding rate arbitrage
    # ------------------------------------------------------------------

    def _detect_funding_rate_arb(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        results: List[InefficiciencySignal] = []
        for tick in bl.fresh_ticks():
            if tick.funding_rate == 0.0:
                continue
            # Annualise: 3× 8-h payments per day × 365
            annualised = abs(tick.funding_rate) * 3 * 365
            if annualised < FUNDING_RATE_ANNUALISED_THRESHOLD:
                continue

            # Positive funding → longs pay shorts → short spot, long futures
            action = SignalAction.SELL.value if tick.funding_rate > 0 else SignalAction.BUY.value
            confidence = min(0.97, 0.60 + (annualised - FUNDING_RATE_ANNUALISED_THRESHOLD) * 0.5)
            profit_bps = annualised * 10_000 / 365   # daily contribution in bps
            profit_usd = 1_000.0 * profit_bps / 10_000.0

            results.append(self._make_signal(
                symbol=symbol,
                itype=InefficiciencyType.FUNDING_RATE_ARB,
                action=action,
                confidence=confidence,
                profit_usd=profit_usd,
                profit_bps=profit_bps,
                description=(
                    f"Funding rate arb on {tick.exchange}: "
                    f"rate={tick.funding_rate:.5f} "
                    f"({annualised*100:.1f}% p.a.)"
                ),
                exchanges=[tick.exchange],
                extra={
                    "funding_rate": tick.funding_rate,
                    "annualised_pct": round(annualised * 100, 2),
                },
            ))
        return results

    # ------------------------------------------------------------------
    # Detection pillar 3: Microstructure shock
    # ------------------------------------------------------------------

    def _detect_microstructure_shock(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        z = bl.spread_z()
        if abs(z) < SPREAD_Z_THRESHOLD:
            return []

        # Wide spread (z > 0) → temporary illiquidity → mean-revert entry
        # Narrow spread (z < 0) → high liquidity → momentum continuation
        action = SignalAction.BUY.value if z > 0 else SignalAction.SELL.value
        confidence = min(0.95, 0.55 + (abs(z) - SPREAD_Z_THRESHOLD) * 0.08)
        profit_bps = abs(z) * 2.0
        profit_usd = 1_000.0 * profit_bps / 10_000.0

        fresh = bl.fresh_ticks()
        exchanges = [t.exchange for t in fresh]

        return [self._make_signal(
            symbol=symbol,
            itype=InefficiciencyType.MICROSTRUCTURE_SHOCK,
            action=action,
            confidence=confidence,
            profit_usd=profit_usd,
            profit_bps=profit_bps,
            description=f"Microstructure shock: spread Z-score={z:.2f}",
            exchanges=exchanges,
            extra={"spread_z": round(z, 4)},
        )]

    # ------------------------------------------------------------------
    # Detection pillar 4: Volume surge anomaly
    # ------------------------------------------------------------------

    def _detect_volume_surge(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        z = bl.volume_z()
        if z < VOLUME_Z_THRESHOLD:
            return []

        confidence = min(0.92, 0.55 + (z - VOLUME_Z_THRESHOLD) * 0.07)
        profit_bps = z * 1.5
        profit_usd = 1_000.0 * profit_bps / 10_000.0
        fresh = bl.fresh_ticks()
        exchanges = [t.exchange for t in fresh]

        # Volume surge generally precedes directional move — bias toward buy
        return [self._make_signal(
            symbol=symbol,
            itype=InefficiciencyType.VOLUME_SURGE,
            action=SignalAction.BUY.value,
            confidence=confidence,
            profit_usd=profit_usd,
            profit_bps=profit_bps,
            description=f"Volume surge detected: Z-score={z:.2f}",
            exchanges=exchanges,
            extra={"volume_z": round(z, 4)},
        )]

    # ------------------------------------------------------------------
    # Detection pillar 5: Latency arbitrage
    # ------------------------------------------------------------------

    def _detect_latency_arbitrage(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        fresh = bl.fresh_ticks()
        if len(fresh) < 2:
            return []

        # Identify slow vs fast venues by latency_ms
        slow = [t for t in fresh if t.latency_ms > LATENCY_ARBITRAGE_MS]
        fast = [t for t in fresh if t.latency_ms <= LATENCY_ARBITRAGE_MS]
        if not slow or not fast:
            return []

        # If slow venue has stale mid that differs from fast-venue mid,
        # there is a latency arbitrage window.
        fast_mid = np.mean([t.mid for t in fast])
        slow_mid = np.mean([t.mid for t in slow])
        if fast_mid <= 0 or slow_mid <= 0:
            return []

        lag_bps = abs(fast_mid - slow_mid) / fast_mid * 10_000
        if lag_bps < 5.0:
            return []

        action = SignalAction.BUY.value if fast_mid > slow_mid else SignalAction.SELL.value
        confidence = min(0.93, 0.60 + lag_bps / 200.0)
        profit_usd = 1_000.0 * lag_bps / 10_000.0

        slow_exchanges = [t.exchange for t in slow]
        fast_exchanges = [t.exchange for t in fast]

        return [self._make_signal(
            symbol=symbol,
            itype=InefficiciencyType.LATENCY_ARBITRAGE,
            action=action,
            confidence=confidence,
            profit_usd=profit_usd,
            profit_bps=lag_bps,
            description=(
                f"Latency arb: fast venues {fast_exchanges} vs "
                f"slow venues {slow_exchanges} — lag={lag_bps:.1f} bps"
            ),
            exchanges=fast_exchanges + slow_exchanges,
            extra={
                "lag_bps": round(lag_bps, 4),
                "fast_venues": fast_exchanges,
                "slow_venues": slow_exchanges,
            },
        )]

    # ------------------------------------------------------------------
    # Detection pillar 6: ML-based reversion signal
    # ------------------------------------------------------------------

    def _detect_ml_reversion(
        self, symbol: str, bl: _SymbolBaseline
    ) -> List[InefficiciencySignal]:
        score = bl.ml_score   # EWM-updated, range ≈ [-1, +1]
        if abs(score) < 0.3:
            return []

        action = SignalAction.BUY.value if score > 0 else SignalAction.SELL.value
        confidence = min(0.90, 0.55 + abs(score) * 0.35)
        profit_bps = abs(score) * 8.0
        profit_usd = 1_000.0 * profit_bps / 10_000.0
        fresh = bl.fresh_ticks()
        exchanges = [t.exchange for t in fresh]

        return [self._make_signal(
            symbol=symbol,
            itype=InefficiciencyType.ML_REVERSION,
            action=action,
            confidence=confidence,
            profit_usd=profit_usd,
            profit_bps=profit_bps,
            description=f"ML reversion model score={score:.3f} → {action.upper()}",
            exchanges=exchanges,
            extra={"ml_score": round(score, 4)},
        )]

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _make_signal(
        self,
        symbol: str,
        itype: InefficiciencyType,
        action: str,
        confidence: float,
        profit_usd: float,
        profit_bps: float,
        description: str,
        exchanges: List[str],
        extra: Dict[str, Any],
    ) -> InefficiciencySignal:
        with self._lock:
            self._signal_counter += 1
            sid = f"MIS-{self._signal_counter:06d}"
        return InefficiciencySignal(
            signal_id=sid,
            symbol=symbol,
            inefficiency_type=itype,
            action=action,
            confidence=confidence,
            expected_profit_usd=profit_usd,
            expected_profit_bps=profit_bps,
            description=description,
            source_exchanges=exchanges,
            extra=extra,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a summary of recent MIS activity."""
        history = list(self._signal_history)
        by_type: Dict[str, int] = defaultdict(int)
        for s in history:
            by_type[s.inefficiency_type.value] += 1

        avg_conf = (
            sum(s.confidence for s in history) / len(history) if history else 0.0
        )
        total_profit_est = sum(s.expected_profit_usd for s in history)

        return {
            "total_signals_generated": sum(self._stats.values()),
            "recent_signals_in_buffer": len(history),
            "signals_by_type": dict(by_type),
            "average_confidence": round(avg_conf, 4),
            "total_estimated_profit_usd": round(total_profit_est, 2),
            "active_symbols_tracked": len(self._baselines),
            "recent_signals": [s.to_dict() for s in list(history)[-10:]],
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_mis_instance: Optional[MarketInefficiciencyScanner] = None
_mis_lock = threading.Lock()


def get_market_inefficiency_scanner() -> MarketInefficiciencyScanner:
    """Return the process-level singleton MarketInefficiciencyScanner."""
    global _mis_instance
    if _mis_instance is None:
        with _mis_lock:
            if _mis_instance is None:
                _mis_instance = MarketInefficiciencyScanner()
    return _mis_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    mis = get_market_inefficiency_scanner()

    symbols = ["BTC-USD", "ETH-USD", "XRP-USD"]

    # Simulate ticks from two exchanges over 30 bars
    for bar in range(30):
        for sym in symbols:
            base = {"BTC-USD": 67_000, "ETH-USD": 3_500, "XRP-USD": 0.60}[sym]
            for exchange, latency, funding in [
                ("coinbase", 20, 0.0001),
                ("binance",  300, -0.0002),   # slow venue for latency arb demo
            ]:
                noise = random.gauss(0, base * 0.001)
                bid = base + noise - base * 0.0005
                ask = base + noise + base * 0.0005
                volume = random.expovariate(1 / 3_000_000)
                if bar == 25 and sym == "BTC-USD":
                    volume *= 8   # inject volume surge
                mis.update_tick(
                    exchange=exchange,
                    symbol=sym,
                    bid=bid,
                    ask=ask,
                    volume_usd=volume,
                    funding_rate=funding,
                    latency_ms=latency,
                )

    signals = mis.scan(symbols)
    print(f"\n🎯 Signals found: {len(signals)}")
    for s in signals:
        print(
            f"  [{s.inefficiency_type.value}] {s.symbol} → {s.action.upper()} "
            f"conf={s.confidence:.2f}  est_profit={s.expected_profit_usd:.4f} USD"
        )

    report = mis.get_report()
    print("\n📊 MIS Report:")
    for k, v in report.items():
        if k != "recent_signals":
            print(f"  {k}: {v}")
