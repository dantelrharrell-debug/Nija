"""
NIJA Market Data Engine
========================

Centralised market data collection, normalisation, and fan-out layer.

Responsibilities
----------------
1. **Symbol Registry** — maintains a canonical list of actively monitored pairs.
2. **Tick Ingestion** — accepts raw OHLCV and quote updates from any adapter
   (Coinbase REST, WebSocket, or CSV replay).
3. **Normalisation** — converts raw exchange payloads to a common
   :class:`NormalisedBar` schema (OHLCV + mid + spread + volume_usd).
4. **Rolling Window** — keeps a configurable in-memory ring-buffer of recent
   bars per symbol for fast indicator computation.
5. **Fan-Out** — notifies registered subscribers (strategies, scanners,
   monitors) whenever a new bar is sealed.
6. **Health Tracking** — records feed latency, staleness, and gap counts;
   exposes a health dashboard.

Public API
----------
::

    from bot.market_data_engine import get_market_data_engine

    engine = get_market_data_engine()

    # Register symbols to track
    engine.register_symbol("BTC-USD")
    engine.register_symbol("ETH-USD")

    # Ingest a raw OHLCV bar (e.g., from Coinbase REST candles)
    engine.ingest_bar("BTC-USD", {
        "time": 1712000000,
        "open": 67000.0, "high": 67500.0, "low": 66800.0,
        "close": 67200.0, "volume": 12.5
    })

    # Subscribe to new bars
    def on_bar(bar):
        print(bar.symbol, bar.close)

    engine.subscribe(on_bar)

    # Retrieve recent bars as pandas DataFrame
    df = engine.get_bars("BTC-USD", n=100)

    # Feed a live quote (for MIS / spread tracking)
    engine.ingest_quote("BTC-USD", exchange="coinbase",
                        bid=67190.0, ask=67210.0, volume_usd=500_000.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("nija.market_data_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BAR_WINDOW: int = 500      # bars kept per symbol
STALE_BAR_SECONDS: float = 300.0  # bar older than this flagged as stale
MAX_SUBSCRIBERS: int = 50


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class NormalisedBar:
    """Single OHLCV bar with derived fields, in a canonical schema."""
    symbol: str
    timestamp: float          # Unix epoch (seconds)
    open: float
    high: float
    low: float
    close: float
    volume: float             # base-asset volume
    volume_usd: float         # approximate USD volume (close × volume)
    mid: float                # (high + low) / 2
    spread_bps: float = 0.0   # best bid-ask spread in bps (from quotes, if available)
    exchange: str = "unknown"

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.timestamp) > STALE_BAR_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "volume_usd": self.volume_usd,
            "mid": self.mid,
            "spread_bps": self.spread_bps,
            "exchange": self.exchange,
        }


@dataclass
class FeedHealth:
    """Per-symbol feed-health statistics."""
    symbol: str
    last_bar_ts: float = 0.0
    total_bars_received: int = 0
    gap_count: int = 0            # number of detected missing bars
    max_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    _latency_sum: float = field(default=0.0, repr=False)
    _latency_count: int = field(default=0, repr=False)

    def update_latency(self, latency_ms: float) -> None:
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self._latency_sum += latency_ms
        self._latency_count += 1
        self.avg_latency_ms = self._latency_sum / self._latency_count

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_bar_ts) > STALE_BAR_SECONDS if self.last_bar_ts else True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "last_bar_utc": (
                datetime.fromtimestamp(self.last_bar_ts, tz=timezone.utc).isoformat()
                if self.last_bar_ts else None
            ),
            "total_bars": self.total_bars_received,
            "gap_count": self.gap_count,
            "max_latency_ms": round(self.max_latency_ms, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "is_stale": self.is_stale,
        }


# ---------------------------------------------------------------------------
# Market Data Engine
# ---------------------------------------------------------------------------

class MarketDataEngine:
    """
    Centralised market data bus.  Ingests raw bars and quotes, normalises
    them, maintains rolling windows, and fans out to subscribers.
    """

    def __init__(self, bar_window: int = DEFAULT_BAR_WINDOW) -> None:
        self._bar_window = bar_window
        self._bars: Dict[str, Deque[NormalisedBar]] = defaultdict(
            lambda: deque(maxlen=self._bar_window)
        )
        self._latest_quote: Dict[str, Dict[str, Any]] = {}   # symbol → quote
        self._health: Dict[str, FeedHealth] = {}
        self._symbols: set = set()
        self._subscribers: List[Callable[[NormalisedBar], None]] = []
        self._lock = threading.Lock()
        logger.info("📡 MarketDataEngine initialised (window=%d bars).", bar_window)

    # ------------------------------------------------------------------
    # Symbol registry
    # ------------------------------------------------------------------

    def register_symbol(self, symbol: str) -> None:
        """Register a symbol for active monitoring."""
        with self._lock:
            if symbol not in self._symbols:
                self._symbols.add(symbol)
                self._health[symbol] = FeedHealth(symbol=symbol)
                logger.debug("📌 Symbol registered: %s", symbol)

    def registered_symbols(self) -> List[str]:
        return sorted(self._symbols)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[NormalisedBar], None]) -> None:
        """Register a callback invoked every time a new bar is sealed."""
        if len(self._subscribers) >= MAX_SUBSCRIBERS:
            logger.warning("⚠️ Max subscribers reached (%d); ignoring.", MAX_SUBSCRIBERS)
            return
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[NormalisedBar], None]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def ingest_bar(
        self,
        symbol: str,
        raw: Dict[str, Any],
        exchange: str = "unknown",
    ) -> Optional[NormalisedBar]:
        """
        Ingest a raw OHLCV bar dict.

        Expected keys (flexible naming)::

            time | timestamp | t  → Unix epoch int/float
            open  | o
            high  | h
            low   | l
            close | c
            volume | v

        Returns the normalised bar, or None if the payload is invalid.
        """
        try:
            ts = float(
                raw.get("time") or raw.get("timestamp") or raw.get("t") or 0
            )
            o = float(raw.get("open") or raw.get("o") or 0)
            h = float(raw.get("high") or raw.get("h") or 0)
            lo = float(raw.get("low") or raw.get("l") or 0)
            c = float(raw.get("close") or raw.get("c") or 0)
            v = float(raw.get("volume") or raw.get("v") or 0)
        except (TypeError, ValueError) as exc:
            logger.warning("⚠️ Invalid bar payload for %s: %s", symbol, exc)
            return None

        if c <= 0:
            return None

        ingest_ts = time.time()
        latency_ms = max(0.0, (ingest_ts - ts) * 1_000) if ts > 0 else 0.0

        bar = NormalisedBar(
            symbol=symbol,
            timestamp=ts if ts > 0 else ingest_ts,
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
            volume_usd=c * v,
            mid=(h + lo) / 2.0,
            exchange=exchange,
        )

        self.register_symbol(symbol)

        with self._lock:
            # Detect gaps
            existing = self._bars[symbol]
            if existing and ts > 0:
                prev_ts = existing[-1].timestamp
                expected_gap = ingest_ts - prev_ts   # rough
                if ts < prev_ts:
                    # Out-of-order — skip
                    return None
                if ts - prev_ts > expected_gap * 2 and prev_ts > 0:
                    self._health[symbol].gap_count += 1

            existing.append(bar)
            self._health[symbol].last_bar_ts = bar.timestamp
            self._health[symbol].total_bars_received += 1
            self._health[symbol].update_latency(latency_ms)
            subscribers = list(self._subscribers)

        # Fan-out outside lock to avoid deadlocks
        for cb in subscribers:
            try:
                cb(bar)
            except Exception as exc:  # noqa: BLE001
                logger.warning("⚠️ Subscriber raised exception: %s", exc)

        return bar

    def ingest_quote(
        self,
        symbol: str,
        exchange: str,
        bid: float,
        ask: float,
        volume_usd: float = 0.0,
        funding_rate: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """
        Ingest a live bid/ask quote.

        This updates the latest quote store and also forwards to the
        MarketInefficiciencyScanner (if available) for anomaly detection.
        """
        self.register_symbol(symbol)
        quote = {
            "exchange": exchange,
            "bid": bid,
            "ask": ask,
            "volume_usd": volume_usd,
            "funding_rate": funding_rate,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }
        with self._lock:
            self._latest_quote[symbol] = quote

        # Forward to MIS
        try:
            from market_inefficiency_scanner import get_market_inefficiency_scanner
            mis = get_market_inefficiency_scanner()
        except ImportError:
            try:
                from bot.market_inefficiency_scanner import get_market_inefficiency_scanner
                mis = get_market_inefficiency_scanner()
            except ImportError:
                mis = None

        if mis is not None:
            mis.update_tick(
                exchange=exchange,
                symbol=symbol,
                bid=bid,
                ask=ask,
                volume_usd=volume_usd,
                funding_rate=funding_rate,
                latency_ms=latency_ms,
            )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_bars(self, symbol: str, n: Optional[int] = None) -> List[NormalisedBar]:
        """Return the *n* most recent bars for *symbol* (all if n is None)."""
        with self._lock:
            bars = list(self._bars.get(symbol, []))
        if n is not None:
            bars = bars[-n:]
        return bars

    def get_bars_as_dataframe(self, symbol: str, n: Optional[int] = None):
        """Return bars as a ``pandas.DataFrame`` (requires pandas)."""
        try:
            import pandas as pd
        except ImportError:
            raise RuntimeError(
            "pandas is required for get_bars_as_dataframe(). "
            "Install with: pip install pandas"
        )
        bars = self.get_bars(symbol, n)
        if not bars:
            return None
        return pd.DataFrame([b.to_dict() for b in bars])

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the most recent quote for *symbol*, or None."""
        with self._lock:
            return self._latest_quote.get(symbol)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Return per-symbol health statistics."""
        with self._lock:
            health = {sym: h.to_dict() for sym, h in self._health.items()}
        stale_count = sum(1 for h in health.values() if h["is_stale"])
        return {
            "total_symbols": len(health),
            "stale_symbols": stale_count,
            "symbols": health,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return a concise summary of engine state."""
        with self._lock:
            total_bars = sum(len(q) for q in self._bars.values())
        return {
            "registered_symbols": len(self._symbols),
            "total_bars_in_memory": total_bars,
            "active_subscribers": len(self._subscribers),
            "bar_window_size": self._bar_window,
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_engine_instance: Optional[MarketDataEngine] = None
_engine_lock = threading.Lock()


def get_market_data_engine(bar_window: int = DEFAULT_BAR_WINDOW) -> MarketDataEngine:
    """Return the process-level singleton MarketDataEngine."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = MarketDataEngine(bar_window=bar_window)
    return _engine_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    engine = get_market_data_engine()
    engine.register_symbol("BTC-USD")
    engine.register_symbol("ETH-USD")

    received: List[NormalisedBar] = []
    engine.subscribe(received.append)

    now = int(time.time())
    for i in range(50):
        bar_time = now - (50 - i) * 60
        for sym, base in [("BTC-USD", 67_000), ("ETH-USD", 3_500)]:
            p = base + random.gauss(0, base * 0.005)
            engine.ingest_bar(sym, {
                "time": bar_time,
                "open": p, "high": p * 1.002, "low": p * 0.998,
                "close": p, "volume": random.uniform(1, 20),
            })
            engine.ingest_quote(sym, "coinbase",
                                bid=p - 5, ask=p + 5, volume_usd=p * 1_000)

    print(f"\n📡 Received {len(received)} bar callbacks")
    print("\n📊 Engine summary:", engine.get_summary())
    health = engine.get_health()
    for sym, h in health["symbols"].items():
        print(f"  {sym}: bars={h['total_bars']}, stale={h['is_stale']}")
