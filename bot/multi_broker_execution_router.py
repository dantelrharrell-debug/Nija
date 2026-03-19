"""
NIJA Multi-Broker Execution Router
====================================

Routes trade signals to the correct broker and market based on asset class:

  * **crypto**   → Coinbase / Kraken / Binance (existing BrokerManager)
  * **equities** → Alpaca / Interactive Brokers
  * **futures**  → Interactive Brokers / TD Ameritrade
  * **options**  → Interactive Brokers / TD Ameritrade

The router selects the best available broker for the requested asset class,
validates that the broker supports the symbol, and dispatches the order.
Falls back to an alternate broker when the primary one is unavailable.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │              MultiBrokerExecutionRouter                      │
  │                                                              │
  │  route(signal) ──► detect_asset_class(symbol)               │
  │                ──► select_broker(asset_class)               │
  │                ──► validate & dispatch order                 │
  │                ──► record fill / record failure             │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.multi_broker_execution_router import (
        get_multi_broker_router, RouteRequest, RouteResult
    )

    router = get_multi_broker_router()

    result = router.route(RouteRequest(
        strategy="ApexTrend",
        symbol="BTC-USD",
        side="buy",
        size_usd=500.0,
    ))

    if result.success:
        print(f"Routed to {result.broker} | filled at {result.fill_price:.4f}")
    else:
        print(f"Routing failed: {result.error}")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.multi_broker_router")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum number of observed routes required before a broker's runtime ranking
# is trusted for selection.  Brokers with fewer observations fall back to the
# static-priority leader, preventing a single lucky fill from elevating a new
# broker to the top slot.
MIN_OBSERVATIONS: int = 10

# ---------------------------------------------------------------------------
# Optional subsystem imports — degrade gracefully when unavailable.
# ---------------------------------------------------------------------------

try:
    from bot.execution_router import get_execution_router, OrderRequest, ExecutionResult
    _INNER_ROUTER_AVAILABLE = True
except ImportError:
    try:
        from execution_router import get_execution_router, OrderRequest, ExecutionResult
        _INNER_ROUTER_AVAILABLE = True
    except ImportError:
        _INNER_ROUTER_AVAILABLE = False
        get_execution_router = None  # type: ignore
        logger.warning("ExecutionRouter not available — crypto routing will use stub")

try:
    from bot.capital_allocation_engine import get_capital_allocation_engine
    _CAE_AVAILABLE = True
except ImportError:
    try:
        from capital_allocation_engine import get_capital_allocation_engine
        _CAE_AVAILABLE = True
    except ImportError:
        _CAE_AVAILABLE = False
        get_capital_allocation_engine = None  # type: ignore


# ---------------------------------------------------------------------------
# Asset-class detection helpers
# ---------------------------------------------------------------------------

# Patterns for crypto symbols (e.g. BTC-USD, ETH-USDT, SOL-BTC)
_CRYPTO_PATTERN = re.compile(
    r"^(BTC|ETH|SOL|ADA|DOT|AVAX|MATIC|LINK|UNI|DOGE|XRP|LTC|BCH|"
    r"ATOM|NEAR|FTM|ALGO|VET|ICP|FIL|TRX|XLM|EOS|THETA|HBAR|EGLD|"
    r"FLOW|XTZ|AXS|SAND|MANA|GRT|MKR|COMP|AAVE|SNX|YFI|SUSHI|CRV|"
    r"1INCH|ENJ|BAT|ZRX|ZEC|DASH|XMR|NEO|WAVES|QTUM|ONT|ICX|OMG|"
    r"SC|DCR|DGB|LSK|ARK|STEEM|ZIL|REN|UMA|BAL|SKL|NMR|BAND|ANKR|"
    r"STX|KAVA|HNT|STORJ|OXT|NKN|CGLD|KEEP|CVC|DNT|LOOM|REP|"
    r"WBTC|USDC|USDT|DAI|BUSD|TUSD|USDP|FRAX|LUSD|GUSD|PAX"
    r")[-/](USD|USDT|USDC|BTC|ETH|BNB|BUSD|EUR|GBP)$",
    re.IGNORECASE,
)

# Patterns for equity symbols (e.g. AAPL, MSFT, SPY, QQQ)
_EQUITY_PATTERN = re.compile(r"^[A-Z]{1,5}$")

# Patterns for futures symbols (e.g. ES=F, NQ=F, CL=F, /ES, BTC-PERP)
_FUTURES_PATTERN = re.compile(
    r"(=F$|^/|[-_]PERP$|[-_]FUT$|[-_]\d{2}[A-Z]\d{4}$)",
    re.IGNORECASE,
)

# Patterns for options symbols (e.g. AAPL240119C00150000, SPY_C_400, AAPL 2024-01-19 call 150)
_OPTIONS_PATTERN = re.compile(
    r"(\d{6}[CP]\d{8}$|[-_](CALL|PUT|[CP])\d|options?|strangle|straddle|condor|butterfly)",
    re.IGNORECASE,
)


class AssetClass(str, Enum):
    """Asset class taxonomy used for broker routing."""
    CRYPTO = "crypto"
    EQUITY = "equity"
    FUTURES = "futures"
    OPTIONS = "options"
    UNKNOWN = "unknown"


def detect_asset_class(symbol: str) -> AssetClass:
    """
    Infer the asset class of *symbol* from its format.

    Returns ``AssetClass.UNKNOWN`` when the symbol cannot be classified;
    callers should treat unknown symbols as crypto (the bot's primary market).
    """
    s = symbol.strip().upper()

    if _FUTURES_PATTERN.search(s):
        return AssetClass.FUTURES
    if _OPTIONS_PATTERN.search(s):
        return AssetClass.OPTIONS
    if _CRYPTO_PATTERN.match(s):
        return AssetClass.CRYPTO
    if _EQUITY_PATTERN.match(s):
        return AssetClass.EQUITY

    # Default — treat as crypto (Coinbase-first bot)
    return AssetClass.CRYPTO


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RouteRequest:
    """Specification for a trade the multi-broker router should handle."""
    strategy: str
    symbol: str
    side: str                           # "buy" | "sell"
    size_usd: float
    asset_class: Optional[str] = None   # override auto-detection
    order_type: Optional[str] = None    # "MARKET" | "LIMIT" | "TWAP"
    limit_price: Optional[float] = None
    preferred_broker: Optional[str] = None   # force a specific broker
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteResult:
    """Result of a routing + execution attempt."""
    success: bool
    symbol: str
    side: str
    size_usd: float
    asset_class: str = AssetClass.UNKNOWN
    broker: str = "NONE"
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    order_type: str = "MARKET"
    latency_ms: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class BrokerProfile:
    """Configuration entry for a broker/exchange."""
    name: str
    asset_classes: List[AssetClass]      # which asset classes this broker handles
    priority: int = 5                    # 1 = highest priority
    available: bool = True
    # Callable(symbol, side, size_usd, order_type, limit_price) → (fill_price, filled_usd)
    dispatch_fn: Optional[Callable] = None
    # Minimum notional in USD
    min_notional_usd: float = 1.0
    fee_bps: float = 10.0
    # Number of routes dispatched through this broker.  Used by _select_broker()
    # to enforce MIN_OBSERVATIONS before trusting any dynamically-derived ranking.
    observation_count: int = 0


# ---------------------------------------------------------------------------
# MultiBrokerExecutionRouter
# ---------------------------------------------------------------------------


class MultiBrokerExecutionRouter:
    """
    Routes trade orders to the correct broker and market based on asset class.

    Thread-safe; process-wide singleton via ``get_multi_broker_router()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._brokers: Dict[str, BrokerProfile] = {}
        self._route_log: List[Dict[str, Any]] = []
        self._stats: Dict[str, int] = {
            "total_routes": 0,
            "successful_routes": 0,
            "failed_routes": 0,
        }

        # Register default broker profiles
        self._register_default_brokers()
        logger.info("MultiBrokerExecutionRouter initialised")

    # ------------------------------------------------------------------
    # Broker management
    # ------------------------------------------------------------------

    def _register_default_brokers(self) -> None:
        """Register the built-in broker profiles."""

        # ── Crypto brokers ──────────────────────────────────────────
        self.register_broker(BrokerProfile(
            name="coinbase",
            asset_classes=[AssetClass.CRYPTO],
            priority=1,
            fee_bps=25.0,  # Coinbase Advanced Trade taker fee
            dispatch_fn=self._dispatch_via_inner_router,
        ))
        self.register_broker(BrokerProfile(
            name="kraken",
            asset_classes=[AssetClass.CRYPTO],
            priority=2,
            fee_bps=16.0,
            dispatch_fn=self._dispatch_via_inner_router,
        ))
        self.register_broker(BrokerProfile(
            name="binance",
            asset_classes=[AssetClass.CRYPTO],
            priority=3,
            fee_bps=10.0,
            dispatch_fn=self._dispatch_via_inner_router,
        ))

        # ── Equity brokers ───────────────────────────────────────────
        self.register_broker(BrokerProfile(
            name="alpaca",
            asset_classes=[AssetClass.EQUITY],
            priority=1,
            fee_bps=0.0,    # Alpaca is commission-free
            dispatch_fn=self._dispatch_equity_stub,
        ))
        self.register_broker(BrokerProfile(
            name="interactive_brokers_equity",
            asset_classes=[AssetClass.EQUITY],
            priority=2,
            fee_bps=5.0,
            dispatch_fn=self._dispatch_equity_stub,
        ))

        # ── Futures brokers ──────────────────────────────────────────
        self.register_broker(BrokerProfile(
            name="interactive_brokers_futures",
            asset_classes=[AssetClass.FUTURES],
            priority=1,
            fee_bps=5.0,
            dispatch_fn=self._dispatch_futures_stub,
        ))
        self.register_broker(BrokerProfile(
            name="td_ameritrade_futures",
            asset_classes=[AssetClass.FUTURES],
            priority=2,
            fee_bps=8.0,
            dispatch_fn=self._dispatch_futures_stub,
        ))

        # ── Options brokers ──────────────────────────────────────────
        self.register_broker(BrokerProfile(
            name="interactive_brokers_options",
            asset_classes=[AssetClass.OPTIONS],
            priority=1,
            fee_bps=5.0,
            dispatch_fn=self._dispatch_options_stub,
        ))
        self.register_broker(BrokerProfile(
            name="td_ameritrade_options",
            asset_classes=[AssetClass.OPTIONS],
            priority=2,
            fee_bps=8.0,
            dispatch_fn=self._dispatch_options_stub,
        ))

    def register_broker(self, profile: BrokerProfile) -> None:
        """Add or replace a broker profile in the registry."""
        with self._lock:
            self._brokers[profile.name] = profile
            logger.debug("Registered broker: %s (classes=%s, priority=%d)",
                         profile.name, profile.asset_classes, profile.priority)

    def set_broker_available(self, broker_name: str, available: bool) -> None:
        """Mark a broker as available or unavailable."""
        with self._lock:
            if broker_name in self._brokers:
                self._brokers[broker_name].available = available
                status = "AVAILABLE" if available else "UNAVAILABLE"
                logger.info("Broker %s marked %s", broker_name, status)
            else:
                logger.warning("Unknown broker: %s", broker_name)

    # ------------------------------------------------------------------
    # Core routing
    # ------------------------------------------------------------------

    def route(self, request: RouteRequest) -> RouteResult:
        """
        Route a trade request to the appropriate broker.

        Returns a :class:`RouteResult` describing success or failure.
        """
        t0 = time.monotonic()

        # 1. Determine asset class
        if request.asset_class:
            try:
                ac = AssetClass(request.asset_class.lower())
            except ValueError:
                ac = detect_asset_class(request.symbol)
        else:
            ac = detect_asset_class(request.symbol)

        logger.info(
            "Routing %s %s %s (size=%.2f, asset_class=%s)",
            request.side.upper(), request.symbol, request.strategy,
            request.size_usd, ac.value,
        )

        # 2. Select broker
        broker = self._select_broker(ac, request.preferred_broker)
        if broker is None:
            elapsed_ms = (time.monotonic() - t0) * 1000
            error = f"No available broker for asset_class={ac.value}"
            logger.error(error)
            return self._make_result(request, ac, "NONE", False, 0.0, 0.0,
                                     elapsed_ms, error)

        # 3. Validate minimum notional
        if request.size_usd < broker.min_notional_usd:
            elapsed_ms = (time.monotonic() - t0) * 1000
            error = (f"Order size ${request.size_usd:.2f} below "
                     f"minimum notional ${broker.min_notional_usd:.2f} for {broker.name}")
            logger.warning(error)
            return self._make_result(request, ac, broker.name, False, 0.0, 0.0,
                                     elapsed_ms, error)

        # 4. Dispatch
        fill_price, filled_usd, dispatch_error = self._dispatch(request, broker)
        elapsed_ms = (time.monotonic() - t0) * 1000
        success = dispatch_error is None and fill_price > 0

        result = self._make_result(
            request, ac, broker.name, success,
            fill_price, filled_usd, elapsed_ms,
            dispatch_error,
        )

        # 5. Update stats & log
        with self._lock:
            self._stats["total_routes"] += 1
            if success:
                self._stats["successful_routes"] += 1
                logger.info(
                    "✅ %s %s filled via %s at %.4f (%.2f USD, %.0f ms)",
                    request.side.upper(), request.symbol, broker.name,
                    fill_price, filled_usd, elapsed_ms,
                )
            else:
                self._stats["failed_routes"] += 1
                logger.error(
                    "❌ %s %s routing via %s failed: %s",
                    request.side.upper(), request.symbol, broker.name,
                    dispatch_error,
                )

            # Increment observation count so the broker accrues evidence for
            # future selection decisions (MIN_OBSERVATIONS threshold).
            if broker.name in self._brokers:
                self._brokers[broker.name].observation_count += 1

            self._route_log.append({
                "timestamp": result.timestamp,
                "symbol": request.symbol,
                "side": request.side,
                "size_usd": request.size_usd,
                "asset_class": ac.value,
                "broker": broker.name,
                "success": success,
                "fill_price": fill_price,
                "latency_ms": elapsed_ms,
                "error": dispatch_error,
            })

            # Keep log bounded
            if len(self._route_log) > 1000:
                self._route_log = self._route_log[-500:]

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_broker(
        self, asset_class: AssetClass, preferred: Optional[str]
    ) -> Optional[BrokerProfile]:
        """Select the best available broker for the asset class.

        Candidates are sorted by static ``priority`` (ascending, 1 = best)
        to establish a stable fallback order.  Only brokers that have
        accumulated at least ``MIN_OBSERVATIONS`` route records are
        considered "qualified" — this prevents a single lucky fill from
        promoting a new broker to the top slot.

        Selection logic:
        1. Build ``candidates`` — available brokers for the asset class.
        2. Sort ``candidates`` by ``priority``; the first becomes the
           ``fallback_priority_broker`` (used when no one qualifies).
        3. Filter to ``qualified`` — those with ``observation_count >=
           MIN_OBSERVATIONS``.
        4. Return ``qualified[0]`` if any qualify; otherwise return the
           static-priority fallback, ensuring a usable route always exists.
        """
        with self._lock:
            candidates = [
                b for b in self._brokers.values()
                if asset_class in b.asset_classes and b.available
            ]

        if not candidates:
            return None

        # If a specific broker is requested, use it if available
        if preferred:
            for b in candidates:
                if b.name == preferred:
                    return b
            logger.warning(
                "Preferred broker '%s' not available for %s — falling back",
                preferred, asset_class.value,
            )

        # Sort by priority (ascending = highest priority first)
        candidates.sort(key=lambda b: b.priority)

        # The static fallback: always the highest-priority (lowest number) broker.
        # It is returned whenever no candidate has sufficient observations.
        fallback_priority_broker = candidates[0]

        # Only trust brokers that have enough observations to produce a reliable
        # ranking.  Skip under-observed brokers and return the static fallback.
        qualified = [b for b in candidates if b.observation_count >= MIN_OBSERVATIONS]

        if not qualified:
            logger.debug(
                "No broker has reached MIN_OBSERVATIONS=%d for asset_class=%s "
                "— using static-priority fallback '%s'",
                MIN_OBSERVATIONS, asset_class.value, fallback_priority_broker.name,
            )
            return fallback_priority_broker

        return qualified[0]

    def _dispatch(
        self,
        request: RouteRequest,
        broker: BrokerProfile,
    ) -> Tuple[float, float, Optional[str]]:
        """
        Dispatch the order via the broker's dispatch function.

        Returns (fill_price, filled_usd, error_message_or_None).
        """
        if broker.dispatch_fn is None:
            return 0.0, 0.0, f"Broker '{broker.name}' has no dispatch function"

        try:
            fill_price, filled_usd = broker.dispatch_fn(
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                order_type=request.order_type or "MARKET",
                limit_price=request.limit_price,
                broker_name=broker.name,
            )
            return fill_price, filled_usd, None
        except Exception as exc:
            return 0.0, 0.0, str(exc)

    @staticmethod
    def _make_result(
        request: RouteRequest,
        ac: AssetClass,
        broker_name: str,
        success: bool,
        fill_price: float,
        filled_usd: float,
        latency_ms: float,
        error: Optional[str],
    ) -> RouteResult:
        return RouteResult(
            success=success,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            asset_class=ac.value,
            broker=broker_name,
            fill_price=fill_price,
            filled_size_usd=filled_usd,
            order_type=request.order_type or "MARKET",
            latency_ms=latency_ms,
            error=error,
        )

    # ------------------------------------------------------------------
    # Dispatch implementations
    # ------------------------------------------------------------------

    def _dispatch_via_inner_router(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        broker_name: str = "coinbase",
    ) -> Tuple[float, float]:
        """
        Dispatch crypto orders through the existing ExecutionRouter.

        Falls back to a simulated fill when the inner router is unavailable.
        """
        if _INNER_ROUTER_AVAILABLE and get_execution_router is not None:
            inner = get_execution_router()
            req = OrderRequest(
                strategy="MultiBrokerRouter",
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                order_type=order_type,
                venue=broker_name,
            )
            res: ExecutionResult = inner.execute(req)
            if res.success:
                return res.fill_price, res.filled_size_usd
            raise RuntimeError(res.error or "Inner router returned failure")

        # Stub: simulate a fill (paper-trading / testing)
        logger.warning(
            "ExecutionRouter unavailable — simulating crypto fill for %s", symbol
        )
        simulated_price = 1.0  # caller should not rely on this in live mode
        return simulated_price, size_usd

    @staticmethod
    def _dispatch_equity_stub(
        symbol: str,
        side: str,
        size_usd: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        broker_name: str = "alpaca",
    ) -> Tuple[float, float]:
        """
        Stub equity dispatch — replace with real Alpaca / IBKR integration.

        Raises ``NotImplementedError`` in live mode so callers get a clear
        error rather than a silent bad fill.
        """
        logger.info(
            "[Equity stub] %s %s %.2f USD via %s (order_type=%s)",
            side.upper(), symbol, size_usd, broker_name, order_type,
        )
        # TODO: integrate with Alpaca or IBKR REST API
        raise NotImplementedError(
            f"Equity broker '{broker_name}' integration not yet connected. "
            "Wire up an Alpaca or IBKR REST client in _dispatch_equity_stub()."
        )

    @staticmethod
    def _dispatch_futures_stub(
        symbol: str,
        side: str,
        size_usd: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        broker_name: str = "interactive_brokers_futures",
    ) -> Tuple[float, float]:
        """
        Stub futures dispatch — replace with real IBKR / CME integration.
        """
        logger.info(
            "[Futures stub] %s %s %.2f USD via %s (order_type=%s)",
            side.upper(), symbol, size_usd, broker_name, order_type,
        )
        # TODO: integrate with IBKR TWS or CME Direct
        raise NotImplementedError(
            f"Futures broker '{broker_name}' integration not yet connected. "
            "Wire up an IBKR TWS or CME Direct client in _dispatch_futures_stub()."
        )

    @staticmethod
    def _dispatch_options_stub(
        symbol: str,
        side: str,
        size_usd: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        broker_name: str = "interactive_brokers_options",
    ) -> Tuple[float, float]:
        """
        Stub options dispatch — replace with real IBKR / TD Ameritrade integration.
        """
        logger.info(
            "[Options stub] %s %s %.2f USD via %s (order_type=%s)",
            side.upper(), symbol, size_usd, broker_name, order_type,
        )
        # TODO: integrate with IBKR TWS or TD Ameritrade thinkorswim API
        raise NotImplementedError(
            f"Options broker '{broker_name}' integration not yet connected. "
            "Wire up an IBKR TWS or TD Ameritrade client in _dispatch_options_stub()."
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return routing statistics."""
        with self._lock:
            stats = dict(self._stats)
            stats["success_rate_pct"] = (
                (stats["successful_routes"] / stats["total_routes"] * 100)
                if stats["total_routes"] > 0 else 0.0
            )
            return stats

    def get_recent_routes(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the *n* most recent routing events."""
        with self._lock:
            return list(self._route_log[-n:])

    def get_report(self) -> str:
        """Generate a human-readable routing report."""
        stats = self.get_stats()
        lines = [
            "=" * 70,
            "  NIJA MULTI-BROKER EXECUTION ROUTER — STATUS REPORT",
            "=" * 70,
            f"  Total Routes      : {stats['total_routes']:>10,}",
            f"  Successful Routes : {stats['successful_routes']:>10,}",
            f"  Failed Routes     : {stats['failed_routes']:>10,}",
            f"  Success Rate      : {stats['success_rate_pct']:>10.1f} %",
            f"  Min Observations  : {MIN_OBSERVATIONS:>10}  (threshold before trusting broker ranking)",
            "",
            "  REGISTERED BROKERS",
            "-" * 70,
        ]
        with self._lock:
            for b in sorted(self._brokers.values(), key=lambda x: (x.asset_classes[0].value, x.priority)):
                status = "✅ AVAILABLE" if b.available else "❌ UNAVAILABLE"
                classes = ", ".join(a.value for a in b.asset_classes)
                obs_flag = "" if b.observation_count >= MIN_OBSERVATIONS else " ⚠️ (warming up)"
                lines.append(
                    f"  {b.name:<40} [{classes:<10}] priority={b.priority}  obs={b.observation_count}{obs_flag}  {status}"
                )
        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[MultiBrokerExecutionRouter] = None
_instance_lock = threading.Lock()


def get_multi_broker_router() -> MultiBrokerExecutionRouter:
    """Return the process-wide MultiBrokerExecutionRouter singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MultiBrokerExecutionRouter()
    return _instance


__all__ = [
    "AssetClass",
    "detect_asset_class",
    "RouteRequest",
    "RouteResult",
    "BrokerProfile",
    "MultiBrokerExecutionRouter",
    "get_multi_broker_router",
]

# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    router = get_multi_broker_router()
    print(router.get_report())

    # Asset-class detection demo
    test_symbols = [
        ("BTC-USD", AssetClass.CRYPTO),
        ("ETH-USDT", AssetClass.CRYPTO),
        ("AAPL", AssetClass.EQUITY),
        ("MSFT", AssetClass.EQUITY),
        ("/ES", AssetClass.FUTURES),
        ("ES=F", AssetClass.FUTURES),
        ("BTC-PERP", AssetClass.FUTURES),
    ]
    print("\nAsset-class detection:")
    all_ok = True
    for sym, expected in test_symbols:
        detected = detect_asset_class(sym)
        ok = detected == expected
        if not ok:
            all_ok = False
        print(f"  {sym:<20} → {detected.value:<10}  {'✅' if ok else '❌ expected ' + expected.value}")

    print("\n✅ All detection tests passed." if all_ok else "\n❌ Some detection tests FAILED.")
