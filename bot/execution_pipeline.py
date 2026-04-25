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
The final connected flow that ties every coordination layer together:

    1. Detect market regime
    2. Update evolution engine
    3. Receive MASTER signal from MasterStrategyRouter
    4. Risk check (global 6 % ceiling via GlobalCapitalManager)
    5. Execute across all accounts via SignalBroadcaster
    6. Record results in AccountPerformanceDashboard & ProfitSplitter

Call ``ExecutionPipeline.run(signal)`` once per valid signal inside the
existing ``TradingStrategy.run_cycle()`` loop — after
``MasterStrategyRouter.update()`` has already stored the signal.

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
    from bot.execution_pipeline import get_execution_pipeline

    pipeline = get_execution_pipeline()
    pipeline.run(signal=analysis, account_id="coinbase", account_balance=5000.0)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

logger = logging.getLogger("nija.execution_pipeline")

try:
    from bot.execution_authority_context import execution_authority_scope
except ImportError:
    try:
        from execution_authority_context import execution_authority_scope
    except ImportError:
        @contextmanager
        def execution_authority_scope():
            yield


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
    available_balance_usd: Optional[float] = None
    price_hint_usd: Optional[float] = None
    account_id: str = "default"


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
# Optional subsystem imports
# ---------------------------------------------------------------------------


def _try_import(primary: str, fallback: str):
    """Import a module by primary path, falling back to fallback path."""
    try:
        import importlib
        return importlib.import_module(primary)
    except ImportError:
        try:
            import importlib
            return importlib.import_module(fallback)
        except ImportError:
            return None


_gcm_mod  = _try_import("global_capital_manager",           "bot.global_capital_manager")
_msr_mod  = _try_import("master_strategy_router",           "bot.master_strategy_router")
_sb_mod   = _try_import("signal_broadcaster",               "bot.signal_broadcaster")
_dash_mod = _try_import("account_performance_dashboard",    "bot.account_performance_dashboard")
_ps_mod   = _try_import("profit_splitter",                  "bot.profit_splitter")
_evo_mod  = _try_import("regime_specific_strategy_evolution","bot.regime_specific_strategy_evolution")
_aic_mod  = _try_import("ai_capital_allocator",             "bot.ai_capital_allocator")

get_global_capital_manager      = getattr(_gcm_mod,  "get_global_capital_manager",      None)
get_master_strategy_router      = getattr(_msr_mod,  "get_master_strategy_router",      None)
get_signal_broadcaster          = getattr(_sb_mod,   "get_signal_broadcaster",          None)
get_account_performance_dashboard = getattr(_dash_mod, "get_account_performance_dashboard", None)
get_profit_splitter             = getattr(_ps_mod,   "get_profit_splitter",             None)
get_regime_specific_strategy_evolution = getattr(_evo_mod, "get_regime_specific_strategy_evolution", None)
get_ai_capital_allocator        = getattr(_aic_mod,  "get_ai_capital_allocator",        None)

_eil_mod = _try_import("execution_integrity_layer", "bot.execution_integrity_layer")
get_execution_integrity_layer = getattr(_eil_mod, "get_execution_integrity_layer", None)


# ---------------------------------------------------------------------------
# ExecutionPipeline
# ---------------------------------------------------------------------------

class ExecutionPipeline:
    """
    Orchestrates the full signal-to-execution flow across all accounts.

    Pipeline steps
    --------------
    1. Detect market regime (passed in from caller)
    2. Update evolution engine with current regime
    3. Read master signal from MasterStrategyRouter
    4. Global risk check — block if 6 % ceiling would be breached
    5. Fan-out execution via SignalBroadcaster
    6. Record results in dashboard + profit splitter
    7. Trigger AI capital reallocation
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ecel_refresh_stop = threading.Event()
        self._ecel_refresh_thread: Optional[threading.Thread] = None
        self._ecel_required = True
        self._ecel_fail_closed = True
        self._throttler = self._load_throttler()
        self._router = self._load_router()
        self._multi_router = self._load_multi_router()
        self._ecel = self._load_ecel()
        self._start_ecel_background_refresh()

        self._run_count: int = 0
        self._blocked_count: int = 0
        self._last_run: Optional[str] = None

        logger.info(
            "ExecutionPipeline initialised | throttler=%s | router=%s | multi_router=%s | "
            "ecel_required=%s | ecel_fail_closed=%s | ecel_loaded=%s",
            self._throttler is not None,
            self._router is not None,
            self._multi_router is not None,
            self._ecel_required,
            self._ecel_fail_closed,
            self._ecel is not None,
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
        reservation_id: Optional[str] = None
        effective_request = request

        if self._ecel is None and self._ecel_required:
            error = "ECEL unavailable: strict execution gate blocks order dispatch"
            logger.error("ExecutionPipeline: %s", error)
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=error,
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        # ECEL pre-trade compile: schema checks, step-size compiler, reservation.
        if self._ecel is not None:
            try:
                broker_hint = (request.preferred_broker or "coinbase").lower()
                compile_req = self._ecel_mod.CompileRequest(  # type: ignore[attr-defined]
                    broker=broker_hint,
                    symbol=request.symbol,
                    side=self._normalise_side(request.side),
                    order_type=(request.order_type or "MARKET").upper(),
                    desired_notional_usd=request.size_usd,
                    available_balance_usd=request.available_balance_usd,
                    price_hint_usd=request.price_hint_usd,
                    account_id=request.account_id,
                )
                compiled = self._ecel.compile(compile_req)
                if not compiled.accepted:
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=f"ECEL reject: {compiled.reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )

                reservation_id = compiled.reservation_id
                effective_request = replace(request, size_usd=compiled.compiled_notional_usd)
            except Exception as exc:
                msg = f"ECEL compile exception: {exc}"
                if self._ecel_fail_closed or self._ecel_required:
                    logger.error("ExecutionPipeline: %s", msg)
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=f"ECEL reject: {msg}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
                logger.warning("ExecutionPipeline: %s; using raw request", msg)

        # ── Priority-2: Trade Throttler ──────────────────────────────────
        if self._throttler is not None:
            try:
                allowed, throttle_reason = self._throttler.check()
                if not allowed:
                    if reservation_id and self._ecel is not None:
                        self._ecel.release_reservation(reservation_id)
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
        with execution_authority_scope():
            result = self._dispatch(effective_request, t_start)

        if reservation_id and self._ecel is not None and not result.success:
            self._ecel.release_reservation(reservation_id)

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
        if self._ecel is not None:
            try:
                schema = self._ecel.schema.as_dict()
                refresh_health = None
                if hasattr(self._ecel.schema, "get_refresh_health"):
                    refresh_health = self._ecel.schema.get_refresh_health()
                status["ecel"] = {
                    "enabled": True,
                    "required": self._ecel_required,
                    "fail_closed": self._ecel_fail_closed,
                    "coinbase_rules": len(schema.get("coinbase", {})),
                    "kraken_rules": len(schema.get("kraken", {})),
                    "background_refresh_thread_alive": bool(
                        self._ecel_refresh_thread and self._ecel_refresh_thread.is_alive()
                    ),
                    "refresh_health": refresh_health,
                }
            except Exception:
                status["ecel"] = {"enabled": True}
        else:
            status["ecel"] = {
                "enabled": False,
                "required": self._ecel_required,
                "fail_closed": self._ecel_fail_closed,
            }
        return status

    def stop_background_tasks(self) -> None:
        """Request graceful stop of background workers."""
        self._ecel_refresh_stop.set()

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

    def _load_ecel(self):
        self._ecel_mod = None
        warm_refresh = os.getenv("ECEL_WARM_REFRESH_ON_STARTUP", "true").strip().lower() in (
            "1", "true", "yes"
        )
        for mod_name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
            try:
                mod = __import__(mod_name, fromlist=["get_ecel_execution_compiler", "CompileRequest"])
                self._ecel_mod = mod
                compiler = mod.get_ecel_execution_compiler()
                if warm_refresh:
                    try:
                        stats = compiler.schema.refresh_from_public_endpoints()
                        logger.info(
                            "ExecutionPipeline: ECEL warm-refresh complete | coinbase=%d | kraken=%d",
                            stats.get("coinbase", 0),
                            stats.get("kraken", 0),
                        )
                    except Exception as exc:
                        logger.warning("ExecutionPipeline: ECEL warm-refresh failed: %s", exc)
                logger.info("ExecutionPipeline: ECEL compiler loaded from %s", mod_name)
                return compiler
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load ECEL module %s: %s", mod_name, exc)
        logger.warning(
            "ExecutionPipeline: ECEL compiler unavailable -- %s",
            "blocking execution (strict mode)" if self._ecel_required else "pre-trade compile disabled",
        )
        return None

    def _start_ecel_background_refresh(self) -> None:
        """Start periodic ECEL schema refresh worker with jitter/backoff."""
        if self._ecel is None:
            return
        ecel = self._ecel

        enabled = os.getenv("ECEL_BACKGROUND_REFRESH_ENABLED", "true").strip().lower() in (
            "1", "true", "yes"
        )
        if not enabled:
            logger.info("ExecutionPipeline: ECEL background refresh disabled by env")
            return

        if self._ecel_refresh_thread and self._ecel_refresh_thread.is_alive():
            return

        interval_s = float(os.getenv("ECEL_BACKGROUND_REFRESH_INTERVAL_S", "900"))
        jitter_s = float(os.getenv("ECEL_BACKGROUND_REFRESH_JITTER_S", "30"))
        max_backoff_s = float(os.getenv("ECEL_BACKGROUND_REFRESH_MAX_BACKOFF_S", "3600"))

        def _worker() -> None:
            failures = 0
            logger.info(
                "ExecutionPipeline: ECEL background refresh started | interval=%.0fs jitter=%.0fs",
                interval_s,
                jitter_s,
            )
            while not self._ecel_refresh_stop.is_set():
                sleep_base = interval_s
                try:
                    stats = ecel.schema.refresh_from_public_endpoints()
                    failures = 0
                    logger.debug(
                        "ExecutionPipeline: ECEL background refresh ok | coinbase=%d kraken=%d",
                        stats.get("coinbase", 0),
                        stats.get("kraken", 0),
                    )
                except Exception as exc:
                    failures += 1
                    sleep_base = min(interval_s * (2 ** min(failures, 6)), max_backoff_s)
                    logger.warning(
                        "ExecutionPipeline: ECEL background refresh failed (%d): %s",
                        failures,
                        exc,
                    )

                jitter = random.uniform(0.0, max(0.0, jitter_s))
                wait_s = max(1.0, sleep_base + jitter)
                self._ecel_refresh_stop.wait(wait_s)

            logger.info("ExecutionPipeline: ECEL background refresh stopped")

        self._ecel_refresh_thread = threading.Thread(
            target=_worker,
            name="nija-ecel-refresh",
            daemon=True,
        )
        self._ecel_refresh_thread.start()

    def run(
        self,
        signal: Dict[str, Any],
        account_id: str = "platform",
        account_balance: float = 0.0,
        regime: str = "RANGING",
        pnl_usd: float = 0.0,
        is_win: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the full pipeline for the given signal.

        Args:
            signal:          Analysis dict (must contain 'action' and 'symbol').
            account_id:      ID of the calling (master) account.
            account_balance: Current balance of the master account.
            regime:          Current market regime label (e.g. 'BULL_TRENDING').
            pnl_usd:         P&L of the just-closed trade, if any (0 = entry).
            is_win:          Whether the last closed trade was a win.

        Returns:
            Result dict with 'status', 'broadcast_results', and metadata.
        """
        with self._lock:
            self._run_count += 1

        result: Dict[str, Any] = {
            "status": "ok",
            "signal_action": signal.get("action", "hold"),
            "symbol": signal.get("symbol", ""),
            "regime": regime,
            "broadcast_results": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        action = signal.get("action", "hold")
        if action not in ("enter_long", "enter_short"):
            result["status"] = "hold"
            return result

        # ── Step 2: Update regime-specific evolution engine ───────────────────
        if get_regime_specific_strategy_evolution:
            try:
                evo = get_regime_specific_strategy_evolution()
                # Prefer set_regime(); fall back to evolve(regime) for older API
                if callable(getattr(evo, "set_regime", None)):
                    evo.set_regime(regime)
                elif callable(getattr(evo, "evolve", None)):
                    evo.evolve(regime)
            except Exception as exc:
                logger.debug("[Pipeline] evo update skipped: %s", exc)

        # ── Step 3: Confirm master signal ─────────────────────────────────────
        if get_master_strategy_router:
            try:
                master_signal = get_master_strategy_router().get_signal()
                if master_signal and master_signal.get("symbol") == signal.get("symbol"):
                    signal = master_signal          # use authoritative master copy
            except Exception as exc:
                logger.debug("[Pipeline] master router read skipped: %s", exc)

        # ── Step 4: Global risk check ─────────────────────────────────────────
        if get_global_capital_manager:
            try:
                gcm = get_global_capital_manager()
                position_size = signal.get("position_size") or 0.0
                requested_risk = (
                    position_size / account_balance
                    if account_balance > 0 and position_size > 0
                    else 0.0
                )
                if requested_risk > 0 and not gcm.can_open_trade(requested_risk):
                    logger.warning(
                        "[Pipeline] BLOCKED_GLOBAL_RISK for %s "
                        "(requested=%.2f%%, total would exceed 6%%)",
                        signal.get("symbol"), requested_risk * 100,
                    )
                    with self._lock:
                        self._blocked_count += 1
                    result["status"] = "BLOCKED_GLOBAL_RISK"
                    return result
                gcm.update_account_risk(account_id, requested_risk)
            except Exception as exc:
                logger.debug("[Pipeline] risk check skipped: %s", exc)

        # ── Step 5: Fan-out execution across accounts ─────────────────────────
        broadcast_results: List[Dict] = []
        if get_signal_broadcaster:
            try:
                sb = get_signal_broadcaster()
                raw_results = sb.execute_across_accounts(signal)
                broadcast_results = [
                    {
                        "account_id": r.account_id,
                        "status": r.status,
                        "size_usd": r.size_usd,
                        "error": r.error,
                    }
                    for r in raw_results
                ]
            except Exception as exc:
                logger.warning("[Pipeline] signal broadcaster error: %s", exc)

        result["broadcast_results"] = broadcast_results

        # ── Step 6: Record performance & profit ───────────────────────────────
        if pnl_usd != 0.0:
            if get_account_performance_dashboard:
                try:
                    get_account_performance_dashboard().record_trade(
                        account_id=account_id,
                        pnl_usd=pnl_usd,
                        is_win=is_win,
                        equity_usd=account_balance,
                    )
                except Exception as exc:
                    logger.debug("[Pipeline] dashboard record skipped: %s", exc)

            if get_profit_splitter:
                try:
                    get_profit_splitter().record_profit(gross_pnl_usd=pnl_usd)
                except Exception as exc:
                    logger.debug("[Pipeline] profit splitter skipped: %s", exc)

        # ── Step 7: AI capital reallocation ───────────────────────────────────
        if get_ai_capital_allocator:
            try:
                get_ai_capital_allocator().update()
            except Exception as exc:
                logger.debug("[Pipeline] AI allocator update skipped: %s", exc)

        # ── Step 8: Fill reconciliation per cycle ─────────────────────────────
        # Reconcile all fills registered against this cycle so underfills that
        # slipped through broker-level checks are surfaced and logged.
        cycle_id = signal.get("cycle_id") or f"pipeline-{self._run_count}"
        if get_execution_integrity_layer is not None:
            try:
                eil = get_execution_integrity_layer()
                reconciliation = eil.reconcile_cycle(cycle_id)
                result["fill_reconciliation"] = reconciliation.to_dict()
                if reconciliation.has_integrity_failures:
                    logger.warning(
                        "[Pipeline] 🔒 FILL RECONCILIATION FAILURE cycle=%s — "
                        "%d underfill(s) out of %d order(s)",
                        cycle_id,
                        reconciliation.underfill_count,
                        reconciliation.total_orders,
                    )
            except Exception as exc:
                logger.debug("[Pipeline] fill reconciliation skipped: %s", exc)

        with self._lock:
            self._last_run = result["timestamp"]

        logger.info(
            "[Pipeline] ✅ %s %s → %d accounts executed (regime=%s)",
            action, signal.get("symbol", ""), len(broadcast_results), regime,
        )
        return result

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "run_count": self._run_count,
                "blocked_count": self._blocked_count,
                "last_run": self._last_run,
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_PIPELINE: Optional[ExecutionPipeline] = None
_PIPELINE_LOCK = threading.Lock()


def get_execution_pipeline() -> ExecutionPipeline:
    """Return the process-wide ExecutionPipeline singleton."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None:
            _PIPELINE = ExecutionPipeline()
            logger.info("[Pipeline] singleton created — full execution pipeline ENABLED")
    return _PIPELINE
