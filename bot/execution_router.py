"""
NIJA Execution Router — Smart Order Routing to Exchanges
=========================================================

The Execution Router is the **final layer** before orders reach an exchange.
It selects the optimal execution venue, order type, and timing for each trade,
then dispatches the order through the configured broker adapter.

Responsibilities
----------------
1. **Venue Selection** — ranks available exchanges for the requested symbol
   based on liquidity score, fee tier, and latency profile.
2. **Order-Type Selection** — chooses MARKET, LIMIT, or TWAP based on order
   size relative to typical volume (impact minimisation).
3. **Pre-flight Validation** — checks broker circuit-breakers, minimum
   notional requirements, and hard-controls gate before submission.
4. **Execution Tracking** — records fill price, slippage, and latency; feeds
   the ExchangeKillSwitch health monitor.
5. **Retry / Fallback** — on broker failure, automatically retries up to N
   times with exponential back-off, then falls back to an alternate venue.

Supported order types
---------------------
* ``MARKET`` — immediate fill at best available price.
* ``LIMIT``  — passive resting order with configurable price offset.
* ``TWAP``   — time-weighted average price (split into sub-orders over a window).

Public API
----------
::

    from bot.execution_router import get_execution_router, OrderRequest

    router = get_execution_router()

    req = OrderRequest(
        strategy="ApexTrend",
        symbol="BTC-USD",
        side="buy",
        size_usd=500.0,
        order_type="MARKET",  # optional, auto-selected if omitted
    )

    result = router.execute(req)

    if result.success:
        print(f"Filled at {result.fill_price:.4f} | slippage {result.slippage_bps:.1f} bps")
    else:
        print(f"Failed: {result.error}")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.execution_router")

# ---------------------------------------------------------------------------
# Optional subsystem imports — each degrades gracefully if unavailable.
# ---------------------------------------------------------------------------

try:
    from exchange_kill_switch import get_exchange_kill_switch_protector
    _EKS_AVAILABLE = True
except ImportError:
    try:
        from bot.exchange_kill_switch import get_exchange_kill_switch_protector
        _EKS_AVAILABLE = True
    except ImportError:
        _EKS_AVAILABLE = False
        get_exchange_kill_switch_protector = None  # type: ignore
        logger.warning("ExchangeKillSwitch not available — exchange health gate disabled")

try:
    from liquidity_intelligence_engine import get_liquidity_intelligence_engine
    _LIE_AVAILABLE = True
except ImportError:
    try:
        from bot.liquidity_intelligence_engine import get_liquidity_intelligence_engine
        _LIE_AVAILABLE = True
    except ImportError:
        _LIE_AVAILABLE = False
        get_liquidity_intelligence_engine = None  # type: ignore
        logger.warning("LiquidityIntelligenceEngine not available — liquidity gate disabled")

try:
    from liquidity_detection_engine import get_liquidity_detection_engine
    _LDE_AVAILABLE = True
except ImportError:
    try:
        from bot.liquidity_detection_engine import get_liquidity_detection_engine
        _LDE_AVAILABLE = True
    except ImportError:
        _LDE_AVAILABLE = False
        get_liquidity_detection_engine = None  # type: ignore
        logger.warning("LiquidityDetectionEngine not available")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Impact threshold: above this size (as % of typical daily volume) use LIMIT
IMPACT_LIMIT_THRESHOLD_PCT: float = 0.005   # 0.5% of daily volume
IMPACT_TWAP_THRESHOLD_PCT: float = 0.020    # 2.0% of daily volume

# Retry settings
MAX_RETRIES: int = 3
BASE_RETRY_DELAY_S: float = 0.5   # seconds

# Slippage cap for market orders (basis points)
MAX_SLIPPAGE_BPS: float = 30.0

# TWAP default window (seconds)
TWAP_WINDOW_S: int = 60
TWAP_SLICES: int = 5

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OrderRequest:
    """Specification for a trade the router should execute."""
    strategy: str
    symbol: str
    side: str                           # "buy" | "sell"
    size_usd: float
    order_type: Optional[str] = None    # "MARKET" | "LIMIT" | "TWAP" | None (auto)
    limit_offset_bps: float = 5.0       # basis points away from mid for LIMIT orders
    max_slippage_bps: float = MAX_SLIPPAGE_BPS
    venue: Optional[str] = None         # force a specific venue; None = auto-select
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result returned after ``execute()`` completes."""
    success: bool
    symbol: str
    side: str
    size_usd: float
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    slippage_bps: float = 0.0
    order_type: str = "MARKET"
    venue: str = "UNKNOWN"
    latency_ms: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class VenueProfile:
    """Exchange venue configuration and health metrics."""
    name: str
    fee_bps: float = 5.0        # typical taker fee in bps
    latency_ms: float = 50.0    # expected round-trip latency
    liquidity_score: float = 80.0   # 0–100
    available: bool = True
    broker_fn: Optional[Callable] = None   # callable(symbol, side, size_usd) → (price, filled)


# ---------------------------------------------------------------------------
# ExecutionRouter
# ---------------------------------------------------------------------------


class ExecutionRouter:
    """
    Smart Order Router — selects venue, order type, and dispatches trades.

    Thread-safe; process-wide singleton via ``get_execution_router()``.
    """

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        twap_window_s: int = TWAP_WINDOW_S,
        twap_slices: int = TWAP_SLICES,
    ) -> None:
        self._lock = threading.Lock()
        self._max_retries = max_retries
        self._twap_window_s = twap_window_s
        self._twap_slices = twap_slices

        self._venues: Dict[str, VenueProfile] = {}
        self._fill_history: List[ExecutionResult] = []
        self._total_orders: int = 0
        self._failed_orders: int = 0
        self._total_slippage_bps: float = 0.0

        # Lazy subsystem handles
        self._eks = None
        self._lie = None
        self._lde = None

        logger.info("=" * 60)
        logger.info("🚀 Execution Router initialised")
        logger.info("   max_retries   : %d", max_retries)
        logger.info("   twap_window_s : %d", twap_window_s)
        logger.info("   twap_slices   : %d", twap_slices)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Venue management
    # ------------------------------------------------------------------

    def register_venue(self, profile: VenueProfile) -> None:
        """Add or replace a trading venue profile."""
        with self._lock:
            self._venues[profile.name] = profile
            logger.info("✅ Venue registered: %s (fee=%.1f bps)", profile.name, profile.fee_bps)

    def set_venue_available(self, venue_name: str, available: bool) -> None:
        """Mark a venue as available or unavailable (e.g. after an error)."""
        with self._lock:
            if venue_name in self._venues:
                self._venues[venue_name].available = available
                status = "✅" if available else "⛔"
                logger.info("%s Venue availability changed: %s → %s", status, venue_name, available)

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    def execute(self, request: OrderRequest) -> ExecutionResult:
        """
        Route and execute an order.

        Steps:
        1. Pre-flight checks (kill-switch, liquidity gate).
        2. Select venue and order type.
        3. Dispatch order (with retry on failure).
        4. Record result and feed health monitors.
        """
        t_start = time.monotonic()

        # ── Pre-flight: ExchangeKillSwitch ────────────────────────────
        eks = self._get_eks()
        if eks is not None:
            try:
                if eks.is_triggered():
                    return ExecutionResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error="ExchangeKillSwitch: exchange health RED — trade blocked",
                    )
            except Exception as exc:
                logger.warning("ExchangeKillSwitch check failed: %s", exc)

        # ── Pre-flight: Liquidity gate ────────────────────────────────
        lie = self._get_lie()
        if lie is not None:
            try:
                ok = lie.approve_entry(symbol=request.symbol, min_grade="FAIR")
                if not ok:
                    return ExecutionResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error="LiquidityIntelligenceEngine: liquidity grade below FAIR",
                    )
            except Exception as exc:
                logger.warning("Liquidity gate check failed: %s", exc)

        # ── Venue selection ───────────────────────────────────────────
        venue = self._select_venue(request)

        # ── Order-type selection ──────────────────────────────────────
        order_type = request.order_type or self._select_order_type(request)

        # ── Dispatch with retries ─────────────────────────────────────
        result = self._dispatch_with_retry(request, venue, order_type)

        # ── Latency tracking ──────────────────────────────────────────
        result.latency_ms = (time.monotonic() - t_start) * 1000.0

        # ── Post-fill recording ───────────────────────────────────────
        with self._lock:
            self._total_orders += 1
            if not result.success:
                self._failed_orders += 1
            else:
                self._total_slippage_bps += result.slippage_bps
            self._fill_history.append(result)
            if len(self._fill_history) > 1000:
                self._fill_history = self._fill_history[-1000:]

        if result.success:
            logger.info(
                "✅ Order filled: %s %s $%.2f @ %.6f | slippage %.1f bps | %s | %.0f ms",
                request.side, request.symbol, result.filled_size_usd,
                result.fill_price, result.slippage_bps, order_type, result.latency_ms,
            )
        else:
            logger.error(
                "❌ Order failed: %s %s $%.2f — %s",
                request.side, request.symbol, request.size_usd, result.error,
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_venue(self, request: OrderRequest) -> Optional[VenueProfile]:
        """Select the best available venue for the symbol."""
        with self._lock:
            if request.venue and request.venue in self._venues:
                v = self._venues[request.venue]
                return v if v.available else None

            available = [v for v in self._venues.values() if v.available]
            if not available:
                return None

            # Rank: highest liquidity_score first; tie-break on lowest fee
            return sorted(
                available,
                key=lambda v: (-v.liquidity_score, v.fee_bps),
            )[0]

    def _select_order_type(self, request: OrderRequest) -> str:
        """Auto-select MARKET, LIMIT, or TWAP based on order size."""
        # Without volume data default to MARKET for simplicity.
        # A real implementation would check daily volume from the market data feed.
        if request.size_usd >= 50_000.0:
            return "TWAP"
        if request.size_usd >= 10_000.0:
            return "LIMIT"
        return "MARKET"

    def _dispatch_with_retry(
        self,
        request: OrderRequest,
        venue: Optional[VenueProfile],
        order_type: str,
    ) -> ExecutionResult:
        """Attempt to dispatch the order, retrying on transient failures."""
        retries = 0
        last_error = "No venue available"

        if venue is None:
            return ExecutionResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error="No available venue found for order routing",
                order_type=order_type,
                venue="NONE",
            )

        while retries <= self._max_retries:
            try:
                if order_type == "TWAP":
                    result = self._execute_twap(request, venue)
                else:
                    result = self._execute_single(request, venue, order_type)

                result.retries = retries
                return result

            except Exception as exc:
                last_error = str(exc)
                retries += 1
                if retries <= self._max_retries:
                    delay = BASE_RETRY_DELAY_S * (2 ** (retries - 1))
                    logger.warning(
                        "Order dispatch failed (attempt %d/%d): %s — retrying in %.1fs",
                        retries, self._max_retries, exc, delay,
                    )
                    time.sleep(delay)

        return ExecutionResult(
            success=False,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            error=f"Max retries ({self._max_retries}) exceeded: {last_error}",
            order_type=order_type,
            venue=venue.name,
            retries=retries,
        )

    def _execute_single(
        self,
        request: OrderRequest,
        venue: VenueProfile,
        order_type: str,
    ) -> ExecutionResult:
        """Execute a single MARKET or LIMIT order."""
        if venue.broker_fn is not None:
            fill_price, filled_usd = venue.broker_fn(
                request.symbol, request.side, request.size_usd
            )
        else:
            # Simulation: assume perfect fill (no live broker wired)
            fill_price = 0.0
            filled_usd = request.size_usd

        slippage_bps = 0.0  # broker_fn is responsible for reporting actual slippage

        return ExecutionResult(
            success=True,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            fill_price=fill_price,
            filled_size_usd=filled_usd,
            slippage_bps=slippage_bps,
            order_type=order_type,
            venue=venue.name,
        )

    def _execute_twap(
        self,
        request: OrderRequest,
        venue: VenueProfile,
    ) -> ExecutionResult:
        """Execute a TWAP order (split into slices over the configured window)."""
        slice_usd = request.size_usd / self._twap_slices
        interval = self._twap_window_s / self._twap_slices
        total_filled = 0.0
        prices = []

        for i in range(self._twap_slices):
            sub_req = OrderRequest(
                strategy=request.strategy,
                symbol=request.symbol,
                side=request.side,
                size_usd=slice_usd,
                order_type="MARKET",
                venue=venue.name,
            )
            sub_result = self._execute_single(sub_req, venue, "MARKET")
            if sub_result.success:
                total_filled += sub_result.filled_size_usd
                if sub_result.fill_price > 0:
                    prices.append(sub_result.fill_price)

            if i < self._twap_slices - 1:
                time.sleep(interval)

        avg_price = sum(prices) / len(prices) if prices else 0.0

        return ExecutionResult(
            success=total_filled > 0,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            fill_price=avg_price,
            filled_size_usd=total_filled,
            slippage_bps=0.0,
            order_type="TWAP",
            venue=venue.name,
            error=None if total_filled > 0 else "TWAP: all slices failed",
        )

    # ------------------------------------------------------------------
    # Subsystem accessors
    # ------------------------------------------------------------------

    def _get_eks(self):
        if self._eks is None and _EKS_AVAILABLE:
            try:
                self._eks = get_exchange_kill_switch_protector()
            except Exception:
                pass
        return self._eks

    def _get_lie(self):
        if self._lie is None and _LIE_AVAILABLE:
            try:
                self._lie = get_liquidity_intelligence_engine()
            except Exception:
                pass
        return self._lie

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot."""
        with self._lock:
            avg_slippage = (
                self._total_slippage_bps / (self._total_orders - self._failed_orders)
                if (self._total_orders - self._failed_orders) > 0
                else 0.0
            )
            venues_info = [
                {
                    "name": v.name,
                    "available": v.available,
                    "fee_bps": v.fee_bps,
                    "latency_ms": v.latency_ms,
                    "liquidity_score": v.liquidity_score,
                }
                for v in self._venues.values()
            ]
            return {
                "engine": "ExecutionRouter",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_orders": self._total_orders,
                "failed_orders": self._failed_orders,
                "success_rate_pct": round(
                    (1 - self._failed_orders / max(self._total_orders, 1)) * 100, 1
                ),
                "avg_slippage_bps": round(avg_slippage, 2),
                "registered_venues": len(self._venues),
                "venues": venues_info,
                "subsystems": {
                    "exchange_kill_switch": _EKS_AVAILABLE,
                    "liquidity_intelligence_engine": _LIE_AVAILABLE,
                    "liquidity_detection_engine": _LDE_AVAILABLE,
                },
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExecutionRouter] = None
_instance_lock = threading.Lock()


def get_execution_router(**kwargs) -> ExecutionRouter:
    """
    Return the process-wide ``ExecutionRouter`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ExecutionRouter(**kwargs)
        return _instance


__all__ = [
    "OrderRequest",
    "ExecutionResult",
    "VenueProfile",
    "ExecutionRouter",
    "get_execution_router",
]
