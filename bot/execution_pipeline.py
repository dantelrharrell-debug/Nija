"""
NIJA Execution Pipeline
========================

Single orchestration layer that wraps ``ExecutionRouter`` /
``MultiBrokerExecutionRouter`` and enforces the **TradeThrottler**
(Priority-2) gate before every order.

Priority gate wired here
-------------------------
::

    TradeThrottler.check()          <-- Priority-2: rate limiting
        |
        PASS --> ExecutionRouter.execute() / MultiBrokerExecutionRouter.route()
        FAIL --> reject (no order sent)

The pipeline is the canonical execution entry point for all internal callers.
Exchange-level pre-flight checks (ExchangeKillSwitch, liquidity gate) that
already live inside ``ExecutionRouter`` are preserved -- the throttler adds an
outer gate layer.

Usage
-----
::

    from bot.execution_pipeline import get_execution_pipeline, PipelineRequest

    pipeline = get_execution_pipeline()

    result = pipeline.execute(PipelineRequest(
        strategy="ApexTrend",
        symbol="BTC-USD",
        side="buy",
        size_usd=500.0,
    ))

    if result.success:
        print(f"Filled at {result.fill_price:.4f}")
        pipeline.record_trade(symbol="BTC-USD")   # register with throttler
    else:
        print(f"Rejected: {result.error}")

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
from typing import Optional

logger = logging.getLogger("nija.execution_pipeline")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class PipelineRequest:
    """Unified order request for the execution pipeline."""

    symbol: str
    side: str                        # "buy" / "sell" / "long" / "short"
    size_usd: float
    strategy: str = ""
    order_type: Optional[str] = None
    asset_class: Optional[str] = None
    preferred_broker: Optional[str] = None


@dataclass
class PipelineResult:
    """Result from the execution pipeline."""

    success: bool
    symbol: str
    side: str
    size_usd: float
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    broker: str = ""
    latency_ms: float = 0.0
    error: str = ""
    throttled: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ExecutionPipeline:
    """Orchestration layer: TradeThrottler (Priority-2) + order routing.

    Thread-safe singleton via ``get_execution_pipeline()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._throttler = self._load_throttler()
        self._router = self._load_router()
        self._multi_router = self._load_multi_router()

        logger.info(
            "ExecutionPipeline initialised | throttler=%s | router=%s | multi_router=%s",
            self._throttler is not None,
            self._router is not None,
            self._multi_router is not None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, request: PipelineRequest) -> PipelineResult:
        """Route an order through the TradeThrottler gate then to execution.

        Parameters
        ----------
        request:
            Order details.

        Returns
        -------
        PipelineResult
            On throttle: ``.success=False``, ``.throttled=True``.
            On execution: reflects fill/failure from the underlying router.
        """
        t_start = time.monotonic()

        # ── Priority-2: Trade Throttler ──────────────────────────────────
        if self._throttler is not None:
            try:
                allowed, throttle_reason = self._throttler.check()
                if not allowed:
                    logger.warning(
                        "ExecutionPipeline THROTTLED | %s %s $%.2f | %s",
                        request.side.upper(), request.symbol,
                        request.size_usd, throttle_reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=throttle_reason,
                        throttled=True,
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                logger.warning("ExecutionPipeline: throttler check failed: %s", exc)

        # ── Route to execution ───────────────────────────────────────────
        result = self._dispatch(request, t_start)

        # Auto-register successful trades with the throttler
        if result.success and self._throttler is not None:
            try:
                self._throttler.record_trade(symbol=request.symbol)
            except Exception as exc:
                logger.warning("ExecutionPipeline: throttler.record_trade failed: %s", exc)

        return result

    def record_trade(self, symbol: str = "") -> None:
        """Manually register a trade with the throttler.

        Call this when you execute a trade through a path that bypasses
        ``ExecutionPipeline.execute()`` (e.g. direct broker calls) so the
        rate-limit counters remain accurate.
        """
        if self._throttler is not None:
            try:
                self._throttler.record_trade(symbol=symbol)
            except Exception as exc:
                logger.warning("ExecutionPipeline.record_trade error: %s", exc)

    def get_status(self) -> dict:
        """Return a status snapshot including throttler counters."""
        status: dict = {"pipeline": "ExecutionPipeline", "active": True}
        if self._throttler is not None:
            try:
                status["throttler"] = self._throttler.get_status()
            except Exception:
                pass
        return status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch(self, request: PipelineRequest, t_start: float) -> PipelineResult:
        """Try MultiBrokerExecutionRouter, then fall back to ExecutionRouter."""

        # --- MultiBrokerExecutionRouter (preferred for multi-venue) ---
        if self._multi_router is not None:
            try:
                from bot.multi_broker_execution_router import RouteRequest  # type: ignore
            except ImportError:
                try:
                    from multi_broker_execution_router import RouteRequest  # type: ignore
                except ImportError:
                    RouteRequest = None

            if RouteRequest is not None:
                try:
                    route_req = RouteRequest(
                        strategy=request.strategy,
                        symbol=request.symbol,
                        side=self._normalise_side(request.side),
                        size_usd=request.size_usd,
                        asset_class=request.asset_class or "",
                        preferred_broker=request.preferred_broker or "",
                    )
                    route_result = self._multi_router.route(route_req)
                    return PipelineResult(
                        success=route_result.success,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        fill_price=getattr(route_result, "fill_price", 0.0),
                        filled_size_usd=getattr(route_result, "filled_size_usd", 0.0),
                        broker=getattr(route_result, "broker", ""),
                        latency_ms=(time.monotonic() - t_start) * 1000,
                        error=getattr(route_result, "error", "") or "",
                    )
                except Exception as exc:
                    logger.warning(
                        "ExecutionPipeline: multi_router failed (%s), trying fallback", exc
                    )

        # --- ExecutionRouter (single-venue fallback) ---
        if self._router is not None:
            try:
                from bot.execution_router import OrderRequest  # type: ignore
            except ImportError:
                try:
                    from execution_router import OrderRequest  # type: ignore
                except ImportError:
                    OrderRequest = None

            if OrderRequest is not None:
                try:
                    order_req = OrderRequest(
                        strategy=request.strategy,
                        symbol=request.symbol,
                        side=self._normalise_side(request.side),
                        size_usd=request.size_usd,
                        order_type=request.order_type,
                    )
                    exec_result = self._router.execute(order_req)
                    return PipelineResult(
                        success=exec_result.success,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        fill_price=getattr(exec_result, "fill_price", 0.0),
                        filled_size_usd=getattr(exec_result, "filled_size_usd", 0.0),
                        latency_ms=(time.monotonic() - t_start) * 1000,
                        error=getattr(exec_result, "error", "") or "",
                    )
                except Exception as exc:
                    logger.error("ExecutionPipeline: router failed: %s", exc)
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=str(exc),
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )

        # No router available
        error = "ExecutionPipeline: no execution router available"
        logger.error(error)
        return PipelineResult(
            success=False,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            error=error,
            latency_ms=(time.monotonic() - t_start) * 1000,
        )

    @staticmethod
    def _normalise_side(side: str) -> str:
        s = side.lower()
        if s in ("long", "buy"):
            return "buy"
        if s in ("short", "sell"):
            return "sell"
        return s

    @staticmethod
    def _load_throttler():
        for mod_name in ("bot.trade_throttler", "trade_throttler"):
            try:
                mod = __import__(mod_name, fromlist=["get_trade_throttler"])
                t = mod.get_trade_throttler()
                logger.info("ExecutionPipeline: TradeThrottler loaded from %s", mod_name)
                return t
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load %s: %s", mod_name, exc)
        logger.warning("ExecutionPipeline: TradeThrottler unavailable -- throttle gate disabled")
        return None

    @staticmethod
    def _load_router():
        for mod_name in ("bot.execution_router", "execution_router"):
            try:
                mod = __import__(mod_name, fromlist=["get_execution_router"])
                r = mod.get_execution_router()
                logger.info("ExecutionPipeline: ExecutionRouter loaded from %s", mod_name)
                return r
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load router %s: %s", mod_name, exc)
        return None

    @staticmethod
    def _load_multi_router():
        for mod_name in ("bot.multi_broker_execution_router", "multi_broker_execution_router"):
            try:
                mod = __import__(mod_name, fromlist=["get_multi_broker_router"])
                r = mod.get_multi_broker_router()
                logger.info("ExecutionPipeline: MultiBrokerRouter loaded from %s", mod_name)
                return r
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load %s: %s", mod_name, exc)
        return None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[ExecutionPipeline] = None
_instance_lock = threading.Lock()


def get_execution_pipeline() -> ExecutionPipeline:
    """Return the process-wide :class:`ExecutionPipeline` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExecutionPipeline()
    return _instance
