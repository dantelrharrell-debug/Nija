"""
NIJA Smart Execution Engine
=============================

Provides institutional-grade order execution algorithms that minimise
market impact by slicing large orders across time and/or multiple venues.

Algorithms implemented
----------------------
TWAP   – Time-Weighted Average Price: splits order into equal slices
         over a given duration, executing each slice at fixed intervals.

VWAP   – Volume-Weighted Average Price: weights each slice in proportion
         to the expected volume profile of the day.

IS     – Implementation Shortfall: minimises total execution cost by
         balancing urgency against market impact using the Almgren-Chriss
         model heuristic.

ICEBERG– Shows only a small visible portion of the total order; suitable
         for illiquid crypto pairs.

Integration with liquidity_routing_system.py
--------------------------------------------
Each slice is passed to the existing LiquidityRoutingSystem (if available)
to find the best venue before final placement. Fallback is direct placement.

Usage
-----
    from bot.smart_execution_engine import SmartExecutionEngine, ExecutionAlgo

    engine = SmartExecutionEngine(broker_client=None)
    plan   = engine.create_execution_plan(
        symbol="BTC-USD",
        side="BUY",
        total_size=1.0,
        algo=ExecutionAlgo.TWAP,
        duration_minutes=30,
        current_price=65_000.0,
    )
    # Execute synchronously (blocks until done)
    results = engine.execute_plan(plan)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.smart_execution")

# Try to import existing routing system
try:
    from bot.liquidity_routing_system import LiquidityRoutingSystem, RoutedOrderPlan
    _ROUTING_AVAILABLE = True
except ImportError:
    try:
        from liquidity_routing_system import LiquidityRoutingSystem, RoutedOrderPlan
        _ROUTING_AVAILABLE = True
    except ImportError:
        _ROUTING_AVAILABLE = False
        LiquidityRoutingSystem = None   # type: ignore
        RoutedOrderPlan = None          # type: ignore


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ExecutionAlgo(str, Enum):
    TWAP     = "TWAP"
    VWAP     = "VWAP"
    IS       = "IMPLEMENTATION_SHORTFALL"
    ICEBERG  = "ICEBERG"
    MARKET   = "MARKET"    # single shot, no slicing


class SliceStatus(str, Enum):
    PENDING   = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED    = "FILLED"
    FAILED    = "FAILED"
    SKIPPED   = "SKIPPED"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OrderSlice:
    """A single execution slice within a larger algorithm plan."""
    slice_id:      int
    symbol:        str
    side:          str           # "BUY" | "SELL"
    size:          float         # units to trade
    scheduled_at:  datetime      # when to fire this slice
    limit_price:   Optional[float] = None
    status:        SliceStatus = SliceStatus.PENDING
    filled_price:  Optional[float] = None
    filled_size:   float = 0.0
    cost_usd:      float = 0.0
    latency_ms:    float = 0.0
    venue:         str = ""
    error:         str = ""
    executed_at:   Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "slice_id": self.slice_id,
            "symbol": self.symbol,
            "side": self.side,
            "size": round(self.size, 8),
            "scheduled_at": self.scheduled_at.isoformat(),
            "limit_price": self.limit_price,
            "status": self.status.value,
            "filled_price": self.filled_price,
            "filled_size": round(self.filled_size, 8),
            "cost_usd": round(self.cost_usd, 4),
            "latency_ms": round(self.latency_ms, 2),
            "venue": self.venue,
            "error": self.error,
            "executed_at": self.executed_at,
        }


@dataclass
class ExecutionPlan:
    """Complete algorithm execution plan for one parent order."""
    plan_id:        str
    symbol:         str
    side:           str
    total_size:     float
    algo:           ExecutionAlgo
    slices:         List[OrderSlice]
    current_price:  float
    expected_cost:  float = 0.0      # estimated total USD cost
    start_time:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time:       Optional[datetime] = None
    status:         str = "PENDING"  # PENDING / RUNNING / COMPLETED / CANCELLED

    # Post-execution summary
    total_filled:   float = 0.0
    avg_fill_price: float = 0.0
    total_cost_usd: float = 0.0
    slippage_bps:   float = 0.0      # basis points vs arrival price
    savings_usd:    float = 0.0      # vs single market order

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "symbol": self.symbol,
            "side": self.side,
            "total_size": round(self.total_size, 8),
            "algo": self.algo.value,
            "current_price": self.current_price,
            "expected_cost": round(self.expected_cost, 4),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "total_filled": round(self.total_filled, 8),
            "avg_fill_price": round(self.avg_fill_price, 4),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "slippage_bps": round(self.slippage_bps, 2),
            "savings_usd": round(self.savings_usd, 4),
            "slices": [s.to_dict() for s in self.slices],
        }


# ---------------------------------------------------------------------------
# Volume profiles (crypto day pattern — normalised to sum=1)
# ---------------------------------------------------------------------------

# Approximate hourly volume weights (UTC) for crypto markets.
# Index 0 = 00:00 UTC, 23 = 23:00 UTC.
CRYPTO_VOLUME_PROFILE = [
    0.031, 0.026, 0.022, 0.020, 0.022, 0.026,
    0.033, 0.041, 0.049, 0.053, 0.056, 0.056,
    0.053, 0.051, 0.049, 0.047, 0.046, 0.049,
    0.051, 0.053, 0.049, 0.046, 0.041, 0.036,
]
assert abs(sum(CRYPTO_VOLUME_PROFILE) - 1.0) < 0.01, f"Profile sums to {sum(CRYPTO_VOLUME_PROFILE):.4f}"


def _volume_weight_for_interval(start: datetime, interval_minutes: int) -> float:
    """Return fraction of daily volume expected in a given time interval."""
    hour = start.hour
    minute_frac = start.minute / 60.0
    # Interpolate between adjacent hours
    w0 = CRYPTO_VOLUME_PROFILE[hour % 24]
    w1 = CRYPTO_VOLUME_PROFILE[(hour + 1) % 24]
    hourly_w = w0 + (w1 - w0) * minute_frac
    return hourly_w * (interval_minutes / 60.0)


# ---------------------------------------------------------------------------
# Smart Execution Engine
# ---------------------------------------------------------------------------

class SmartExecutionEngine:
    """
    Slices and routes large orders using configurable execution algorithms.

    Args:
        broker_client: Live broker client (Coinbase RESTClient, etc.).
                       If None, all orders are simulated.
        routing_system: Optional pre-configured LiquidityRoutingSystem.
        on_slice_filled: Optional callback(slice: OrderSlice) called after
                         each slice is executed.
        impact_factor: Linear market-impact coefficient (fraction of size
                       that shifts price, per unit of ADV). Used by IS algo.
    """

    def __init__(
        self,
        broker_client=None,
        routing_system=None,
        on_slice_filled: Optional[Callable[[OrderSlice], None]] = None,
        impact_factor: float = 0.1,
        simulation_mode: bool = True,
    ):
        self._broker = broker_client
        self._router: Optional[LiquidityRoutingSystem] = routing_system
        self._on_slice_filled = on_slice_filled
        self.impact_factor = impact_factor
        self.simulation_mode = (broker_client is None) or simulation_mode

        self._plans: Dict[str, ExecutionPlan] = {}
        self._lock = threading.Lock()
        self._plan_counter = 0

    # ------------------------------------------------------------------
    # Plan creation
    # ------------------------------------------------------------------

    def create_execution_plan(
        self,
        symbol: str,
        side: str,
        total_size: float,
        algo: ExecutionAlgo = ExecutionAlgo.TWAP,
        current_price: float = 0.0,
        duration_minutes: int = 30,
        num_slices: Optional[int] = None,
        iceberg_show_pct: float = 0.10,
    ) -> ExecutionPlan:
        """
        Build an execution plan (list of OrderSlices) without submitting.

        Args:
            symbol: Trading pair, e.g. "BTC-USD".
            side: "BUY" or "SELL".
            total_size: Total units to trade.
            algo: Execution algorithm.
            current_price: Current mid-price (arrival price).
            duration_minutes: Time horizon for TWAP/VWAP/IS (ignored for MARKET).
            num_slices: Override automatic slice count.
            iceberg_show_pct: Visible fraction for ICEBERG algo.

        Returns:
            ExecutionPlan (not yet submitted).
        """
        with self._lock:
            self._plan_counter += 1
            plan_id = f"PLAN_{self._plan_counter:05d}_{symbol}"

        algo_enum = ExecutionAlgo(algo) if isinstance(algo, str) else algo

        if algo_enum == ExecutionAlgo.MARKET:
            slices = self._build_market_slice(symbol, side, total_size, current_price)
        elif algo_enum == ExecutionAlgo.TWAP:
            slices = self._build_twap_slices(symbol, side, total_size, duration_minutes, num_slices, current_price)
        elif algo_enum == ExecutionAlgo.VWAP:
            slices = self._build_vwap_slices(symbol, side, total_size, duration_minutes, num_slices, current_price)
        elif algo_enum == ExecutionAlgo.IS:
            slices = self._build_is_slices(symbol, side, total_size, duration_minutes, current_price)
        elif algo_enum == ExecutionAlgo.ICEBERG:
            slices = self._build_iceberg_slices(symbol, side, total_size, iceberg_show_pct, current_price)
        else:
            slices = self._build_market_slice(symbol, side, total_size, current_price)

        plan = ExecutionPlan(
            plan_id=plan_id,
            symbol=symbol,
            side=side,
            total_size=total_size,
            algo=algo_enum,
            slices=slices,
            current_price=current_price,
            expected_cost=total_size * current_price,
        )

        with self._lock:
            self._plans[plan_id] = plan

        logger.info("[SmartExec] Plan %s: %s %s %.4f via %s (%d slices)",
                    plan_id, side, symbol, total_size, algo_enum.value, len(slices))
        return plan

    # ------------------------------------------------------------------
    # Slice builders
    # ------------------------------------------------------------------

    def _build_market_slice(self, symbol, side, size, price) -> List[OrderSlice]:
        return [OrderSlice(0, symbol, side, size, datetime.now(timezone.utc), None)]

    def _build_twap_slices(self, symbol, side, total_size, duration_min, num_slices, price) -> List[OrderSlice]:
        n = num_slices or max(3, duration_min // 5)   # one slice every ~5 min
        slice_size = total_size / n
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=duration_min / n)
        slices = []
        for i in range(n):
            scheduled = now + interval * i
            # Add small limit buffer around arrival price (±0.1 %)
            limit = price * (1.001 if side == "BUY" else 0.999) if price > 0 else None
            slices.append(OrderSlice(i, symbol, side, slice_size, scheduled, limit))
        return slices

    def _build_vwap_slices(self, symbol, side, total_size, duration_min, num_slices, price) -> List[OrderSlice]:
        n = num_slices or max(3, duration_min // 5)
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=duration_min / n)
        # Compute raw volume weights for each slice window
        weights = []
        for i in range(n):
            t = now + interval * i
            weights.append(_volume_weight_for_interval(t, int(duration_min / n)))
        total_w = sum(weights) or 1.0
        slices = []
        for i, w in enumerate(weights):
            frac = w / total_w
            size_i = total_size * frac
            scheduled = now + interval * i
            limit = price * (1.001 if side == "BUY" else 0.999) if price > 0 else None
            slices.append(OrderSlice(i, symbol, side, size_i, scheduled, limit))
        return slices

    def _build_is_slices(self, symbol, side, total_size, duration_min, price) -> List[OrderSlice]:
        """
        Almgren-Chriss heuristic: front-load execution to reduce timing risk.
        Uses a geometric decay so that earlier slices are larger.
        """
        n = max(3, duration_min // 5)
        decay = 0.7   # each slice = 0.7 × previous
        raw = [decay ** i for i in range(n)]
        total_raw = sum(raw)
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=duration_min / n)
        slices = []
        for i, r in enumerate(raw):
            frac = r / total_raw
            size_i = total_size * frac
            scheduled = now + interval * i
            # IS uses more aggressive limit to close quickly
            limit = price * (1.002 if side == "BUY" else 0.998) if price > 0 else None
            slices.append(OrderSlice(i, symbol, side, size_i, scheduled, limit))
        return slices

    def _build_iceberg_slices(self, symbol, side, total_size, show_pct, price) -> List[OrderSlice]:
        """Show only show_pct of total; continuously replace as filled."""
        visible_size = total_size * show_pct
        n = math.ceil(1.0 / show_pct)
        now = datetime.now(timezone.utc)
        slices = []
        for i in range(n):
            remaining = total_size - visible_size * i
            size_i = min(visible_size, remaining)
            if size_i <= 0:
                break
            # Iceberg slices fire immediately (market watches for fills)
            scheduled = now + timedelta(seconds=i * 2)
            slices.append(OrderSlice(i, symbol, side, size_i, scheduled, price))
        return slices

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_plan(
        self,
        plan: ExecutionPlan,
        on_complete: Optional[Callable[[ExecutionPlan], None]] = None,
        blocking: bool = True,
    ) -> ExecutionPlan:
        """
        Execute all slices in the plan, respecting scheduled times.

        Args:
            plan: ExecutionPlan from create_execution_plan().
            on_complete: Optional callback when plan is finished.
            blocking: If True, waits until all slices are done.

        Returns:
            Updated ExecutionPlan with fill statistics.
        """
        if blocking:
            self._run_plan(plan, on_complete)
        else:
            t = threading.Thread(target=self._run_plan, args=(plan, on_complete), daemon=True)
            t.start()
        return plan

    def _run_plan(self, plan: ExecutionPlan, on_complete=None) -> None:
        plan.status = "RUNNING"
        arrival_price = plan.current_price

        for sl in plan.slices:
            now = datetime.now(timezone.utc)
            wait_secs = (sl.scheduled_at - now).total_seconds()
            if wait_secs > 0 and not self.simulation_mode:
                logger.debug("[SmartExec] %s slice %d waiting %.1fs", plan.plan_id, sl.slice_id, wait_secs)
                time.sleep(min(wait_secs, 60))

            self._execute_slice(sl, plan.symbol, plan.side, arrival_price)

            if self._on_slice_filled:
                try:
                    self._on_slice_filled(sl)
                except Exception as exc:
                    logger.warning("[SmartExec] on_slice_filled error: %s", exc)

        self._finalise_plan(plan, arrival_price)
        if on_complete:
            try:
                on_complete(plan)
            except Exception as exc:
                logger.warning("[SmartExec] on_complete error: %s", exc)

    def _execute_slice(self, sl: OrderSlice, symbol: str, side: str, arrival_price: float) -> None:
        """Place a single slice via broker or routing system."""
        t0 = time.monotonic()
        sl.status = SliceStatus.SUBMITTED

        try:
            if self.simulation_mode:
                # Simulate fill with tiny random slippage
                import random
                slippage = random.gauss(0, 0.0003)   # 3 bps std dev
                sim_price = arrival_price * (1 + slippage) if side == "BUY" else arrival_price * (1 - slippage)
                sim_price = max(sim_price, 0.01)
                sl.filled_price = sim_price
                sl.filled_size  = sl.size
                sl.cost_usd     = sim_price * sl.size
                sl.venue        = "simulation"
                sl.status       = SliceStatus.FILLED
            elif _ROUTING_AVAILABLE and self._router:
                plan_resp = self._router.route_order(symbol, side, sl.size)
                # LiquidityRoutingSystem returns a RoutedOrderPlan
                sl.filled_price = getattr(plan_resp, "average_price", arrival_price)
                sl.filled_size  = sl.size
                sl.cost_usd     = sl.filled_price * sl.filled_size
                sl.venue        = "multi_venue"
                sl.status       = SliceStatus.FILLED
            elif self._broker:
                resp = self._broker.place_order(symbol, side, sl.size)
                sl.filled_price = resp.get("filled_price", arrival_price)
                sl.filled_size  = resp.get("filled_size", sl.size)
                sl.cost_usd     = sl.filled_price * sl.filled_size
                sl.venue        = "direct"
                sl.status       = SliceStatus.FILLED if resp.get("status") != "ERROR" else SliceStatus.FAILED
                sl.error        = resp.get("error", "")
            else:
                sl.status = SliceStatus.SKIPPED
                sl.error  = "No broker or router configured"

        except Exception as exc:
            sl.status = SliceStatus.FAILED
            sl.error  = str(exc)
            logger.error("[SmartExec] Slice %d failed: %s", sl.slice_id, exc)

        sl.latency_ms  = (time.monotonic() - t0) * 1000
        sl.executed_at = datetime.now(timezone.utc).isoformat()

    def _finalise_plan(self, plan: ExecutionPlan, arrival_price: float) -> None:
        filled_slices = [s for s in plan.slices if s.status == SliceStatus.FILLED]

        plan.total_filled   = sum(s.filled_size for s in filled_slices)
        plan.total_cost_usd = sum(s.cost_usd for s in filled_slices)

        if plan.total_filled > 0:
            plan.avg_fill_price = plan.total_cost_usd / plan.total_filled
        else:
            plan.avg_fill_price = 0.0

        if arrival_price > 0 and plan.avg_fill_price > 0:
            if plan.side == "BUY":
                slippage = (plan.avg_fill_price - arrival_price) / arrival_price
            else:
                slippage = (arrival_price - plan.avg_fill_price) / arrival_price
            plan.slippage_bps = slippage * 10_000

        # Savings vs a naive single market order (assume 1 % impact on full size)
        naive_impact = plan.current_price * plan.total_size * 0.01
        actual_impact = abs(plan.slippage_bps / 10_000) * plan.total_cost_usd
        plan.savings_usd = max(0.0, naive_impact - actual_impact)
        plan.status       = "COMPLETED"
        plan.end_time     = datetime.now(timezone.utc)

        logger.info(
            "[SmartExec] Plan %s COMPLETE: filled=%.4f avg=%.4f slippage=%.1f bps savings=$%.2f",
            plan.plan_id, plan.total_filled, plan.avg_fill_price,
            plan.slippage_bps, plan.savings_usd,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def plan_summary(self, plan_id: str) -> Optional[Dict]:
        with self._lock:
            plan = self._plans.get(plan_id)
        return plan.to_dict() if plan else None

    def all_plans_summary(self) -> List[Dict]:
        with self._lock:
            return [p.to_dict() for p in self._plans.values()]

    def aggregate_stats(self) -> Dict:
        with self._lock:
            plans = list(self._plans.values())

        completed = [p for p in plans if p.status == "COMPLETED"]
        total_savings  = sum(p.savings_usd for p in completed)
        avg_slippage   = (
            sum(p.slippage_bps for p in completed) / len(completed) if completed else 0.0
        )
        return {
            "total_plans": len(plans),
            "completed_plans": len(completed),
            "total_savings_usd": round(total_savings, 4),
            "avg_slippage_bps": round(avg_slippage, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[SmartExecutionEngine] = None
_engine_lock = threading.Lock()


def get_smart_execution_engine(
    broker_client=None,
    routing_system=None,
    simulation_mode: bool = True,
    reset: bool = False,
) -> SmartExecutionEngine:
    """Return module-level singleton SmartExecutionEngine."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None or reset:
            _engine_instance = SmartExecutionEngine(
                broker_client=broker_client,
                routing_system=routing_system,
                simulation_mode=simulation_mode,
            )
    return _engine_instance
