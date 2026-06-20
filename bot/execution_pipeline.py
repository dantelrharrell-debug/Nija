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

import concurrent.futures
import logging
import os
import random
import threading
import time
from decimal import Decimal
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

logger = logging.getLogger("nija.execution_pipeline")

try:
    from bot.pipeline_request_contract import (
        PipelineRequest,
        normalize_pipeline_request,
        validate_pipeline_request,
    )
except ImportError:
    try:
        from pipeline_request_contract import (  # type: ignore[import]
            PipelineRequest,
            normalize_pipeline_request,
            validate_pipeline_request,
        )
    except ImportError:
        @dataclass(frozen=True)
        class PipelineRequest:  # type: ignore[no-redef]
            symbol: str
            side: str
            size_usd: float
            strategy: str = ""
            order_type: Optional[str] = None
            asset_class: Optional[str] = None
            preferred_broker: Optional[str] = None
            available_balance_usd: Optional[float] = None
            price_hint_usd: Optional[float] = None
            bid_price_usd: Optional[float] = None
            ask_price_usd: Optional[float] = None
            volume_24h_usd: Optional[float] = None
            volatility_pct: Optional[float] = None
            account_id: str = "default"
            validated: bool = False

        def normalize_pipeline_request(value):  # type: ignore[no-redef]
            return value

        def validate_pipeline_request(_):  # type: ignore[no-redef]
            return True, "ok"

try:
    from bot.runtime_correlation import get_runtime_correlation
except ImportError:
    try:
        from runtime_correlation import get_runtime_correlation  # type: ignore[import]
    except ImportError:
        def get_runtime_correlation() -> Dict[str, str]:  # type: ignore[no-redef]
            return {}

try:
    from bot.execution_journal import append_execution_journal_event
except ImportError:
    try:
        from execution_journal import append_execution_journal_event  # type: ignore[import]
    except ImportError:
        def append_execution_journal_event(  # type: ignore[no-redef]
            event_type: str,
            intent_id: str,
            payload: Optional[Dict[str, Any]] = None,
            ts: Optional[str] = None,
        ) -> None:
            return None

# Downstream blocker classifier — imported here for use in _on_order_rejected.
try:
    from bot.downstream_blocker_guard import (
        BlockerType,
        ExchangeErrorClassifier,
        get_downstream_blocker_guard,
    )
except ImportError:
    try:
        from downstream_blocker_guard import (  # type: ignore[import]
            BlockerType,
            ExchangeErrorClassifier,
            get_downstream_blocker_guard,
        )
    except ImportError:
        # Minimal stubs so the pipeline compiles without the guard module.
        class BlockerType:  # type: ignore[no-redef]
            UNKNOWN = "unknown"
        class ExchangeErrorClassifier:  # type: ignore[no-redef]
            @staticmethod
            def classify(error: str):
                return BlockerType.UNKNOWN
            @staticmethod
            def is_soft_blocker(b) -> bool:
                return False
        def get_downstream_blocker_guard():
            return None

_RETRYABLE_EXCHANGE_ERROR_KEYWORDS = (
    "rate limit",
    "too many requests",
    "too many errors",
    "429",
    "temporarily unavailable",
    "try again",
)

try:
    from bot.execution_authority_context import (
        execution_authority_scope,
        can_execute,
        emit_pretrade_execution_validator_trace,
        assert_distributed_writer_authority,
        assert_execution_dispatch_permitted,
        runtime_authority_snapshot,
        ExecutionBlocked,
    )
except ImportError:
    try:
        from execution_authority_context import (  # type: ignore[import]
            execution_authority_scope,
            can_execute,
            emit_pretrade_execution_validator_trace,
            assert_distributed_writer_authority,
            assert_execution_dispatch_permitted,
            runtime_authority_snapshot,
            ExecutionBlocked,
        )
    except ImportError:
        @contextmanager
        def execution_authority_scope():
            yield

        def can_execute():
            class _Decision:
                allowed = False
                reason = "execution_authority_unavailable"
            return _Decision()

        def emit_pretrade_execution_validator_trace(*args, **kwargs):
            return None

        def assert_distributed_writer_authority() -> None:  # type: ignore[no-redef]
            return None

        def assert_execution_dispatch_permitted() -> None:  # type: ignore[no-redef]
            return None

        def runtime_authority_snapshot():  # type: ignore[no-redef]
            class _Snap:
                ready = False
            return _Snap()

        class ExecutionBlocked(RuntimeError):  # type: ignore[no-redef]
            pass

try:
    from bot.exchange_kill_switch import get_exchange_kill_switch_protector
except ImportError:
    try:
        from exchange_kill_switch import get_exchange_kill_switch_protector  # type: ignore[import]
    except ImportError:
        get_exchange_kill_switch_protector = None  # type: ignore[assignment]

try:
    from bot.single_execution_authority_kernel import get_seak
except ImportError:
    try:
        from single_execution_authority_kernel import get_seak  # type: ignore[import]
    except ImportError:
        get_seak = None  # type: ignore[assignment]

try:
    from bot.margin_position_ledger import get_margin_position_ledger
except ImportError:
    try:
        from margin_position_ledger import get_margin_position_ledger  # type: ignore[import]
    except ImportError:
        get_margin_position_ledger = None  # type: ignore[assignment]

try:
    from bot.execution_broker_capabilities import get_broker_capability_registry
except ImportError:
    try:
        from execution_broker_capabilities import get_broker_capability_registry  # type: ignore[import]
    except ImportError:
        get_broker_capability_registry = None  # type: ignore[assignment]

try:
    from bot.margin_health_gate import MarginHealthGate, MarginHealthSnapshot
except ImportError:
    try:
        from margin_health_gate import MarginHealthGate, MarginHealthSnapshot  # type: ignore[import]
    except ImportError:
        MarginHealthGate = None  # type: ignore[assignment]
        MarginHealthSnapshot = None  # type: ignore[assignment]

try:
    from bot.exchange_capabilities import EXCHANGE_CAPABILITIES
except ImportError:
    try:
        from exchange_capabilities import EXCHANGE_CAPABILITIES  # type: ignore[import]
    except ImportError:
        EXCHANGE_CAPABILITIES = None  # type: ignore[assignment]

try:
    from bot.kraken_margin_engine import get_margin_engine
except ImportError:
    try:
        from kraken_margin_engine import get_margin_engine  # type: ignore[import]
    except ImportError:
        get_margin_engine = None  # type: ignore[assignment]

# Optional import — used for cycle_id cross-validation at dispatch time.
# The pipeline must remain importable even when nija_core_loop is absent.
def _get_pipeline_cycle_snapshot():
    """Return the active CycleSnapshot or None when unavailable."""
    try:
        try:
            from bot.nija_core_loop import get_current_cycle_snapshot as _gcs
        except ImportError:
            from nija_core_loop import get_current_cycle_snapshot as _gcs  # type: ignore[import]
        return _gcs()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class PipelineRequest:
    """Unified order request for the execution pipeline."""

    symbol: str
    side: str                        # "buy" / "sell" / "long" / "short"
    size_usd: float
    request_id: Optional[str] = None
    intent_id: Optional[str] = None
    notional_usd: Optional[float] = None
    sizing_mode: str = "notional_usd"
    intent_type: str = "entry"       # "entry" / "reduce" / "exit"
    subaccount_id: Optional[str] = None
    buying_power_usd: Optional[float] = None
    strategy: str = ""
    order_type: Optional[str] = "market"
    asset_class: Optional[str] = None
    instrument_type: Optional[str] = None
    quantity_mode: str = "usd"
    shares: Optional[float] = None
    contracts: Optional[float] = None
    preferred_broker: Optional[str] = None
    available_balance_usd: Optional[float] = None
    price_hint_usd: Optional[float] = None
    bid_price_usd: Optional[float] = None
    ask_price_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    volatility_pct: Optional[float] = None
    account_id: str = "default"
    account_type: Optional[str] = None
    leverage: Optional[float] = None
    reduce_only: bool = False
    position_effect: Optional[str] = None
    borrow_intent: Optional[str] = None
    margin_mode: Optional[str] = None
    maintenance_margin_ratio: Optional[float] = None
    liquidation_buffer_ratio: Optional[float] = None
    borrow_available: Optional[bool] = None
    time_in_force: Optional[str] = None
    extended_hours: Optional[bool] = None
    strategy_metadata: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    validated: bool = False

    def __post_init__(self) -> None:
        # Keep the legacy local request class compatible with the canonical
        # pipeline_request_contract validator.  Many call sites still construct
        # PipelineRequest(size_usd=...) directly; without mirroring that value into
        # notional_usd the contract rejects the order before authority/dispatch
        # gates can run, which blocks all market-order submission.
        if self.notional_usd is None and self.size_usd is not None:
            self.notional_usd = float(self.size_usd)
        if not self.sizing_mode:
            self.sizing_mode = "notional_usd"

        # Runtime order submitters historically pass exchange-style uppercase
        # values (for example order_type="MARKET") and side aliases such as
        # long/short.  The canonical request contract is intentionally strict
        # and validates lowercase enums.  Normalize here so live orders are not
        # rejected at the local contract gate before they ever reach broker
        # dispatch.
        self.side = self._normalise_side(self.side)
        self.order_type = self._normalise_enum(self.order_type) or "market"
        self.intent_type = self._normalise_enum(self.intent_type) or "entry"
        self.sizing_mode = self._normalise_enum(self.sizing_mode) or "notional_usd"
        self.asset_class = self._normalise_enum(self.asset_class)
        self.quantity_mode = self._normalise_enum(self.quantity_mode) or "usd"
        self.account_type = self._normalise_enum(self.account_type)
        self.margin_mode = self._normalise_enum(self.margin_mode)
        self.time_in_force = self._normalise_enum(self.time_in_force)

    @staticmethod
    def _normalise_enum(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    @classmethod
    def _normalise_side(cls, value: Any) -> str:
        side = cls._normalise_enum(value) or "buy"
        if side == "long":
            return "buy"
        if side == "short":
            return "sell"
        return side


# Ensure normalize_pipeline_request accepts the local PipelineRequest class above,
# since it may have been imported from pipeline_request_contract which uses isinstance
# against its own class.  Wrap it to pass through local instances unchanged.
_upstream_normalize = normalize_pipeline_request


def normalize_pipeline_request(value: Any) -> "PipelineRequest":  # type: ignore[no-redef]
    if isinstance(value, PipelineRequest):
        return value
    return _upstream_normalize(value)  # type: ignore[return-value]


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
        self._pre_trade_risk_engine = self._load_pre_trade_risk_engine()
        self._exchange_normalizer = self._load_exchange_normalizer()
        self._allocation_clamp = self._load_allocation_clamp()
        self._execution_observer = self._load_execution_observer()
        self._throttler = self._load_throttler()
        self._router = self._load_router()
        self._multi_router = self._load_multi_router()
        self._margin_health_gate = self._load_margin_health_gate()
        self._capability_matrix = EXCHANGE_CAPABILITIES
        self._ecel = self._load_ecel()
        self._downstream_guard = self._load_downstream_guard()
        self._margin_position_ledger = self._load_margin_position_ledger()
        self._broker_capability_registry = self._load_broker_capability_registry()
        self._start_ecel_background_refresh()
        self._start_margin_position_sync_loop()

        # ACK timeout: max seconds to wait for the broker to acknowledge an order.
        self._ack_timeout_s: float = float(
            os.getenv("NIJA_ACK_TIMEOUT_S", "30")
        )

        self._run_count: int = 0
        self._blocked_count: int = 0
        self._last_run: Optional[str] = None

        logger.info(
            "ExecutionPipeline initialised | throttler=%s | router=%s | multi_router=%s | "
            "pre_trade_risk=%s | exchange_normalizer=%s | allocation_clamp=%s | execution_observer=%s | "
            "margin_ledger=%s | broker_capability_registry=%s | ecel_required=%s | ecel_fail_closed=%s | ecel_loaded=%s",
            self._throttler is not None,
            self._router is not None,
            self._multi_router is not None,
            self._pre_trade_risk_engine is not None,
            self._exchange_normalizer is not None,
            self._allocation_clamp is not None,
            self._execution_observer is not None,
            self._margin_position_ledger is not None,
            self._broker_capability_registry is not None,
            self._ecel_required,
            self._ecel_fail_closed,
            self._ecel is not None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _deny(request: PipelineRequest, t_start: float, reason: str) -> PipelineResult:
        logger.error(
            "🚫 [Pipeline.deny] ORDER DROPPED | symbol=%s side=%s size_usd=%.2f reason=%s",
            getattr(request, "symbol", "?"),
            getattr(request, "side", "?"),
            float(getattr(request, "size_usd", 0.0) or 0.0),
            reason,
        )
        return PipelineResult(
            success=False,
            symbol=request.symbol,
            side=request.side,
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            error=reason,
            latency_ms=(time.monotonic() - t_start) * 1000,
        )

    def _enforce_execution_gate(
        self,
        request: PipelineRequest,
        t_start: float,
    ) -> Optional[PipelineResult]:
        """Gate execution based on SafetyController + TradingStateMachine."""
        safety_mod = _try_import("bot.safety_controller", "safety_controller")
        if safety_mod is None:
            logger.warning("ExecutionPipeline: safety_controller unavailable; skipping safety gate")
            return None

        get_safety_controller = getattr(safety_mod, "get_safety_controller", None)
        TradingMode = getattr(safety_mod, "TradingMode", None)
        if get_safety_controller is None or TradingMode is None:
            logger.warning("ExecutionPipeline: safety_controller missing expected exports; skipping safety gate")
            return None

        safety = get_safety_controller()
        try:
            if hasattr(safety, "recheck_mode"):
                safety.recheck_mode()
        except Exception as exc:
            logger.debug("ExecutionPipeline: safety.recheck_mode() skipped: %s", exc)

        mode = safety.get_current_mode()
        allowed, reason = safety.is_trading_allowed()
        mode_value = mode.value if mode is not None else "unknown"

        logger.info(
            "🔍 [ExecutionGate] safety_mode=%s allowed=%s reason=%s symbol=%s",
            mode_value, allowed, reason, request.symbol,
        )

        if mode in (TradingMode.DISABLED, TradingMode.MONITOR):
            logger.warning(
                "🚫 [ExecutionGate] BLOCKED by safety mode=%s | symbol=%s side=%s size_usd=%.2f",
                mode_value, request.symbol, request.side, request.size_usd,
            )
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=reason or f"Trading blocked (mode={mode_value})",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        if mode in (TradingMode.APP_STORE, TradingMode.DRY_RUN):
            logger.info(
                "🔄 [ExecutionGate] Simulating execution mode=%s | symbol=%s side=%s size_usd=%.2f",
                mode_value, request.symbol, request.side, request.size_usd,
            )
            return self._simulate_execution(request, t_start, mode_value, reason)

        if not allowed:
            logger.warning(
                "🚫 [ExecutionGate] BLOCKED: not allowed | mode=%s reason=%s | symbol=%s side=%s size_usd=%.2f",
                mode_value, reason, request.symbol, request.side, request.size_usd,
            )
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=reason or f"Trading blocked (mode={mode_value})",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        if mode == TradingMode.LIVE:
            try:
                state_mod = _try_import("bot.trading_state_machine", "trading_state_machine")
                if state_mod is None:
                    raise ImportError("trading_state_machine not available")
                get_state_machine = getattr(state_mod, "get_state_machine", None)
                if get_state_machine is None:
                    raise ImportError("get_state_machine not available")
                state_machine = get_state_machine()
                if hasattr(state_machine, "can_dispatch_trades") and not state_machine.can_dispatch_trades():
                    current_state = getattr(state_machine, "get_current_state", lambda: None)()
                    state_value = current_state.value if current_state else "unknown"
                    logger.warning(
                        "🚫 [ExecutionGate] BLOCKED by state_machine | state=%s | symbol=%s side=%s size_usd=%.2f",
                        state_value, request.symbol, request.side, request.size_usd,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=f"Execution gate pending (state_machine={state_value})",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
                else:
                    logger.info(
                        "✅ [ExecutionGate] state_machine gate PASSED | symbol=%s side=%s",
                        request.symbol, request.side,
                    )
            except Exception as exc:
                logger.warning("ExecutionPipeline: trading_state_machine gate skipped: %s", exc)

        return None

    def _gate_capital_margin_authorization(
        self,
        request: PipelineRequest,
        t_start: float,
    ) -> Optional[PipelineResult]:
        side = str(getattr(request, "side", "")).lower()
        sizing_mode = str(getattr(request, "sizing_mode", "") or "")
        notional = float(getattr(request, "notional_usd", 0.0) or 0.0)
        if notional <= 0 and sizing_mode == "notional_usd":
            notional = float(getattr(request, "size_usd", 0.0) or 0.0)

        ledger_row: Dict[str, Any] = {}
        margin_ledger = getattr(self, "_margin_position_ledger", None)
        if margin_ledger is not None:
            try:
                ledger_row = margin_ledger.get_record(
                    broker=str(getattr(request, "preferred_broker", None) or "coinbase"),
                    account_id=str(getattr(request, "account_id", "default") or "default"),
                    subaccount_id=str(getattr(request, "subaccount_id", "") or ""),
                    symbol=str(getattr(request, "symbol", "") or ""),
                    asset_class=str(getattr(request, "asset_class", None) or "crypto"),
                )
            except Exception as exc:
                return self._deny(request, t_start, f"CapitalAuthorization deny: ledger_read_error:{exc}")

        exposure_required = side in ("buy", "long")
        # Only block on missing ledger state for margin/leveraged orders.
        # Spot (leverage=1, no margin_mode) orders do not require a ledger record —
        # blocking them here is the primary cause of zero trade execution on
        # accounts that have not yet opened a margin position.
        _is_margin_order = bool(
            getattr(request, "leverage", 1) and int(getattr(request, "leverage", 1) or 1) > 1
            or getattr(request, "margin_mode", None)
            or getattr(request, "borrow_intent", None)
            or str(getattr(request, "account_type", "") or "").lower() == "margin"
        )
        if exposure_required and notional > 0 and margin_ledger is not None and not ledger_row and _is_margin_order:
            logger.warning(
                "CapitalAuthorization: missing ledger state for margin order — "
                "symbol=%s side=%s notional=%.2f broker=%s account_id=%s",
                getattr(request, "symbol", ""),
                side,
                notional,
                getattr(request, "preferred_broker", ""),
                getattr(request, "account_id", ""),
            )
            return self._deny(request, t_start, "CapitalAuthorization deny: missing_ledger_state")

        buying_power = ledger_row.get("buying_power_usd") if ledger_row else getattr(request, "buying_power_usd", None)
        available_margin = ledger_row.get("available_margin_usd") if ledger_row else getattr(request, "available_balance_usd", None)
        financial_cap = buying_power if buying_power is not None else available_margin
        if exposure_required and notional > 0 and financial_cap is not None and float(financial_cap) < notional:
            return self._deny(request, t_start, "CapitalAuthorization deny: insufficient_buying_power")

        leverage = int(getattr(request, "leverage", 1) or 1)
        ledger_leverage = int(ledger_row.get("leverage") or 1) if ledger_row else 1
        if leverage > ledger_leverage and ledger_row:
            return self._deny(request, t_start, "CapitalAuthorization deny: leverage_exceeds_ledger")

        margin_mode = str(ledger_row.get("margin_mode") or "")
        reduce_only = getattr(request, "reduce_only", None)
        intent_type = str(getattr(request, "intent_type", "") or "").lower()
        if leverage > 1:
            if margin_mode not in ("cross", "isolated"):
                return self._deny(request, t_start, "CapitalAuthorization deny: invalid_margin_mode")
            if intent_type == "entry" and reduce_only is not False:
                return self._deny(request, t_start, "CapitalAuthorization deny: reduce_only_false_required_for_entry")
            if intent_type in ("reduce", "exit") and reduce_only is not True:
                return self._deny(request, t_start, "CapitalAuthorization deny: reduce_only_true_required_for_reduce")
        return None

    def _simulate_execution(
        self,
        request: PipelineRequest,
        t_start: float,
        mode_value: str,
        reason: str,
    ) -> PipelineResult:
        """Return a simulated PipelineResult when in dry-run/app-store mode."""
        dry_run_mod = _try_import("bot.dry_run_engine", "dry_run_engine")
        if dry_run_mod is None:
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=f"{mode_value} active but dry-run engine unavailable",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )
        get_dry_run_engine = getattr(dry_run_mod, "get_dry_run_engine", None)
        if get_dry_run_engine is None:
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=f"{mode_value} active but dry-run engine unavailable",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        app_store_mod = _try_import("bot.app_store_mode", "app_store_mode")
        if app_store_mod is not None and mode_value == "app_store":
            get_app_store_mode = getattr(app_store_mod, "get_app_store_mode", None)
            if get_app_store_mode is not None:
                try:
                    get_app_store_mode().block_execution_with_log(
                        operation="execution_pipeline",
                        symbol=request.symbol,
                        side=request.side,
                        size=request.size_usd,
                    )
                except Exception as exc:
                    logger.debug("ExecutionPipeline: app_store_mode log skipped: %s", exc)

        price_hint = request.price_hint_usd
        if price_hint is None or price_hint <= 0:
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error="Simulation requires price_hint_usd to compute quantity",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )
        # price_hint_usd is expected to be USD per unit of the asset.
        quantity = request.size_usd / price_hint
        order_type = (request.order_type or "market").lower()

        side = request.side.lower().strip()
        if side == "long":
            side = "buy"
        elif side == "short":
            side = "sell"

        engine = get_dry_run_engine()
        try:
            order = engine.place_order(
                symbol=request.symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price_hint if order_type == "limit" else None,
                current_market_price=price_hint if order_type == "market" else None,
            )
            fill_price = order.average_fill_price if order.average_fill_price > 0 else price_hint
            filled_usd = order.filled_quantity * fill_price
        except Exception as exc:
            logger.warning("ExecutionPipeline: simulation failed: %s", exc)
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error=f"Simulation failed: {exc}",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        logger.info(
            "ExecutionPipeline SIMULATED | mode=%s | %s %s $%.2f | reason=%s",
            mode_value,
            request.side.upper(),
            request.symbol,
            request.size_usd,
            reason or "simulation",
        )
        return PipelineResult(
            success=True,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            fill_price=fill_price,
            filled_size_usd=filled_usd,
            broker=f"{mode_value}_simulated",
            latency_ms=(time.monotonic() - t_start) * 1000,
        )

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
        canonical_request = normalize_pipeline_request(request)
        if not getattr(canonical_request, "strategy", ""):
            canonical_request = replace(canonical_request, strategy="unknown_strategy")

        # ── Diagnostic: log every order entering the pipeline ─────────────────
        _ft_active_diag = (
            os.getenv("FORCE_TRADE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
            or os.getenv("FORCE_TRADE_MODE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
        )
        logger.info(
            "📥 [Pipeline.execute] ORDER RECEIVED | symbol=%s side=%s size_usd=%.2f "
            "strategy=%s broker=%s account_id=%s force_trade=%s",
            getattr(canonical_request, "symbol", "?"),
            getattr(canonical_request, "side", "?"),
            float(getattr(canonical_request, "size_usd", 0.0) or 0.0),
            getattr(canonical_request, "strategy", "?"),
            getattr(canonical_request, "preferred_broker", "?"),
            getattr(canonical_request, "account_id", "?"),
            _ft_active_diag,
        )

        valid, reason = validate_pipeline_request(canonical_request)
        if not valid:
            logger.warning("📥 [Pipeline.execute] RequestContract DENY | reason=%s", reason)
            return self._deny(canonical_request, t_start, f"RequestContract deny: {reason}")

        working_request = canonical_request
        effective_request = canonical_request
        order_validated = False
        compiled = None

        gate_result = self._enforce_execution_gate(canonical_request, t_start)
        if gate_result is not None:
            return gate_result

        intent_type = str(getattr(canonical_request, "intent_type", "") or "").strip().lower()
        should_persist_pending = intent_type not in {"reduce", "exit"}
        if should_persist_pending and getattr(self, "_margin_position_ledger", None) is not None:
            try:
                self._margin_position_ledger.apply_submit(canonical_request)
            except Exception as exc:
                return self._deny(canonical_request, t_start, f"OrderFeasibility deny: ledger_submit_error:{exc}")

        gate_result = self._gate_capital_margin_authorization(canonical_request, t_start)
        if gate_result is not None:
            return gate_result

        if self._execution_observer is not None:
            try:
                suppressed, suppression_reason = self._execution_observer.is_strategy_suppressed(canonical_request.strategy)
                if suppressed:
                    return self._deny(canonical_request, t_start, f"OrderFeasibility deny: {suppression_reason}")
            except Exception as exc:
                return self._deny(canonical_request, t_start, f"OrderFeasibility deny: observer_error:{exc}")

        if self._execution_observer is not None and self._allocation_clamp is not None:
            try:
                allocation_multiplier = self._execution_observer.get_allocation_multiplier(request.strategy)
                requested_with_feedback = float(request.size_usd) * allocation_multiplier
                clamp_result = self._allocation_clamp.clamp(
                    requested_usd=requested_with_feedback,
                    baseline_usd=float(canonical_request.size_usd or 0.0),
                )
                working_request = replace(
                    working_request,
                    size_usd=clamp_result.clamped_usd,
                    notional_usd=clamp_result.clamped_usd,
                )
            except Exception as exc:
                return self._deny(canonical_request, t_start, f"OrderFeasibility deny: allocation_clamp_error:{exc}")

        if self._exchange_normalizer is not None:
            try:
                quantity_value = working_request.size_usd
                if working_request.quantity_mode == "shares" and working_request.shares is not None:
                    quantity_value = float(working_request.shares)
                elif working_request.quantity_mode == "contracts" and working_request.contracts is not None:
                    quantity_value = float(working_request.contracts)
                normalized = self._exchange_normalizer.normalize(
                    symbol=working_request.symbol,
                    side=self._normalise_side(working_request.side),
                    broker=(working_request.preferred_broker or "coinbase"),
                    size_usd=working_request.size_usd,
                    price_hint_usd=working_request.price_hint_usd,
                    asset_class=working_request.asset_class,
                    quantity_mode=working_request.quantity_mode,
                    quantity=quantity_value,
                    account_type=working_request.account_type,
                    leverage=working_request.leverage,
                    reduce_only=working_request.reduce_only,
                    position_effect=working_request.position_effect,
                    borrow_intent=working_request.borrow_intent,
                    margin_mode=working_request.margin_mode,
                    time_in_force=working_request.time_in_force,
                    extended_hours=working_request.extended_hours,
                )
                if not normalized.accepted:
                    logger.error(
                        "🚫 [Pipeline] ExchangeNormalizer reject | symbol=%s side=%s size_usd=%.2f reason=%s",
                        working_request.symbol,
                        working_request.side,
                        float(working_request.size_usd or 0.0),
                        normalized.reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"ExchangeNormalizer reject: {normalized.reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
                working_request = replace(
                    working_request,
                    symbol=normalized.native_symbol or normalized.symbol,
                    side=normalized.side,
                    size_usd=normalized.normalized_notional_usd,
                    preferred_broker=normalized.broker,
                )
            except Exception as exc:
                return self._deny(canonical_request, t_start, f"OrderFeasibility deny: normalizer_error:{exc}")

        capability_matrix = getattr(self, "_capability_matrix", None)
        broker_for_caps = (working_request.preferred_broker or "coinbase").lower()
        margin_engine = get_margin_engine() if get_margin_engine is not None else None
        runtime_capability_overrides: Dict[str, Any] = {}
        if margin_engine is not None:
            try:
                runtime_capability_overrides = margin_engine.get_runtime_capability_overrides(
                    account_id=working_request.account_id
                ) or {}
            except Exception:
                runtime_capability_overrides = {}
        if capability_matrix is not None:
            try:
                allowed, reason = capability_matrix.enforce_order_capabilities(
                    broker=broker_for_caps,
                    symbol=working_request.symbol,
                    side=self._normalise_side(working_request.side),
                    asset_class=working_request.asset_class,
                    account_type=working_request.account_type,
                    leverage=working_request.leverage,
                    margin_mode=working_request.margin_mode,
                    runtime_overrides=runtime_capability_overrides,
                )
                if not allowed:
                    logger.error(
                        "🚫 [Pipeline] CapabilityMatrix reject | symbol=%s side=%s broker=%s reason=%s",
                        working_request.symbol,
                        working_request.side,
                        broker_for_caps,
                        reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"CapabilityMatrix reject: {reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                logger.warning("ExecutionPipeline: capability check failed: %s", exc)

        margin_gate = getattr(self, "_margin_health_gate", None)
        margin_requested = bool(
            working_request.margin_mode
            or (working_request.leverage is not None and float(working_request.leverage) > 1.0)
            or working_request.borrow_intent
            or working_request.account_type == "margin"
        )
        if margin_requested and margin_gate is not None:
            try:
                # Deterministic authority boundary:
                # ledger/margin-engine is the source of risk truth; execution gates consume it.
                if margin_engine is not None:
                    reduce_intent = bool(
                        working_request.reduce_only
                        or str(working_request.position_effect or "").lower() in {"close", "close_only", "reduce"}
                    )
                    ledger_allowed, ledger_reason = margin_engine.is_margin_trade_allowed(
                        is_reducing=reduce_intent,
                        adapter=None,
                    )
                    if not ledger_allowed:
                        return PipelineResult(
                            success=False,
                            symbol=working_request.symbol,
                            side=working_request.side,
                            size_usd=working_request.size_usd,
                            error=f"MarginLedger reject: {ledger_reason}",
                            latency_ms=(time.monotonic() - t_start) * 1000,
                        )
                    ledger_snapshot = margin_engine.get_health_snapshot(adapter=None)
                else:
                    ledger_snapshot = None

                snapshot = None
                if MarginHealthSnapshot is not None:
                    inferred_buying_power = (
                        float(ledger_snapshot.free_margin_usd)
                        if ledger_snapshot is not None and ledger_snapshot.free_margin_usd > 0
                        else float(
                            working_request.available_balance_usd
                            if working_request.available_balance_usd is not None
                            else 0.0
                        )
                    )
                    if ledger_snapshot is not None and ledger_snapshot.margin_level_pct > 0:
                        inferred_maintenance_ratio = min(1.0, max(0.0, 100.0 / ledger_snapshot.margin_level_pct))
                    else:
                        inferred_maintenance_ratio = float(working_request.maintenance_margin_ratio or 0.0)
                    snapshot = MarginHealthSnapshot(
                        buying_power_usd=inferred_buying_power,
                        maintenance_margin_ratio=inferred_maintenance_ratio,
                        liquidation_buffer_ratio=float(
                            (
                                0.0 if ledger_snapshot is not None and ledger_snapshot.critical_margin_breach
                                else (
                                    0.05
                                    if ledger_snapshot is not None and not ledger_snapshot.maintenance_margin_ok
                                    else (
                                        1.0 if working_request.liquidation_buffer_ratio is None
                                        else working_request.liquidation_buffer_ratio
                                    )
                                )
                            )
                        ),
                        borrow_available=bool(
                            (
                                not ledger_snapshot.critical_margin_breach and ledger_snapshot.maintenance_margin_ok
                                if ledger_snapshot is not None
                                else (True if working_request.borrow_available is None else working_request.borrow_available)
                            )
                        ),
                    )
                decision = margin_gate.assess(
                    requested_notional_usd=float(working_request.size_usd),
                    side=self._normalise_side(working_request.side),
                    leverage=working_request.leverage,
                    reduce_only=working_request.reduce_only,
                    borrow_intent=working_request.borrow_intent,
                    snapshot=snapshot,
                )
                if not decision.allowed:
                    with execution_authority_scope():
                        auth_decision = can_execute()
                    emit_pretrade_execution_validator_trace(
                        auth_decision,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size=working_request.size_usd,
                        terminal_surface="execution_pipeline_margin_gate",
                        block_reason_code="margin_health_gate_reject",
                        block_reason_detail=str(decision.reason),
                        first_failed_gate="margin.critical_ok",
                    )
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"MarginHealthGate reject: {decision.reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                logger.warning("ExecutionPipeline: margin health gate failed: %s", exc)

        if self._pre_trade_risk_engine is not None:
            try:
                risk_decision = self._pre_trade_risk_engine.assess(
                    account_id=working_request.account_id,
                    symbol=working_request.symbol,
                    size_usd=working_request.size_usd,
                    available_balance_usd=working_request.available_balance_usd,
                )
                if not risk_decision.approved:
                    with execution_authority_scope():
                        auth_decision = can_execute()
                    emit_pretrade_execution_validator_trace(
                        auth_decision,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size=working_request.size_usd,
                        terminal_surface="execution_pipeline_pre_trade_risk",
                        block_reason_code="pre_trade_risk_reject",
                        block_reason_detail=str(risk_decision.reason),
                        first_failed_gate="risk.pre_trade",
                    )
                    logger.error(
                        "🚫 [Pipeline] PreTradeRiskEngine reject | symbol=%s side=%s size_usd=%.2f reason=%s",
                        working_request.symbol,
                        working_request.side,
                        float(working_request.size_usd or 0.0),
                        risk_decision.reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"PreTradeRiskEngine reject: {risk_decision.reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                return self._deny(canonical_request, t_start, f"OrderFeasibility deny: pre_trade_risk_error:{exc}")

        if self._ecel is None and self._ecel_required:
            error = "ECEL unavailable: strict execution gate blocks order dispatch"
            logger.error("ExecutionPipeline: %s", error)
            return PipelineResult(
                success=False,
                symbol=working_request.symbol,
                side=working_request.side,
                size_usd=working_request.size_usd,
                error=error,
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        # ECEL pre-trade compile: schema checks, step-size compiler, reservation.
        if self._ecel is not None:
            try:
                broker_hint = (working_request.preferred_broker or "coinbase").lower()
                compile_req = self._ecel_mod.CompileRequest(  # type: ignore[attr-defined]
                    broker=broker_hint,
                    symbol=working_request.symbol,
                    side=self._normalise_side(working_request.side),
                    order_type=(working_request.order_type or "MARKET").upper(),
                    desired_notional_usd=float(working_request.size_usd or 0.0),
                    sizing_mode=getattr(working_request, "sizing_mode", None),
                    desired_units=getattr(working_request, "units", None),
                    unit_type=getattr(working_request, "unit_type", None),
                    leverage=getattr(working_request, "leverage", None),
                    reduce_only=getattr(working_request, "reduce_only", None),
                    margin_mode=getattr(working_request, "margin_mode", None),
                    intent_type=getattr(working_request, "intent_type", None),
                    price_hint_usd=working_request.price_hint_usd,
                    account_id=working_request.account_id,
                )
                compiled = self._ecel.compile(compile_req)
                if not compiled.accepted:
                    logger.error(
                        "🚫 [Pipeline] ECEL reject | symbol=%s side=%s size_usd=%.2f reason=%s",
                        working_request.symbol,
                        working_request.side,
                        float(working_request.size_usd or 0.0),
                        compiled.reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"ECEL reject: {compiled.reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )

                effective_request = replace(
                    working_request,
                    size_usd=compiled.compiled_notional_usd,
                    notional_usd=compiled.compiled_notional_usd,
                    units=compiled.compiled_base_size,
                    validated=True,
                )
                order_validated = True
            except Exception as exc:
                msg = f"ECEL compile exception: {exc}"
                if self._ecel_fail_closed or self._ecel_required:
                    logger.error("ExecutionPipeline: %s", msg)
                    return PipelineResult(
                        success=False,
                        symbol=working_request.symbol,
                        side=working_request.side,
                        size_usd=working_request.size_usd,
                        error=f"ECEL reject: {msg}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
                logger.warning("ExecutionPipeline: %s; using raw request", msg)

        if self._ecel_required:
            assert order_validated is True, "FATAL: Order bypassed ECEL"
            assert effective_request.validated is True, "FATAL: Order bypassed ECEL"

        self._log_ecel_final_order(request=effective_request, compiled=compiled)

        gate_result = self._gate_broker_capabilities(effective_request, t_start)
        if gate_result is not None:
            return gate_result

        # ── Gate 5: Execution dispatch control (throttling eligibility) ───
        if self._throttler is not None:
            try:
                allowed, throttle_reason = self._throttler.check()
                if not allowed:
                    logger.warning(
                        "ExecutionPipeline THROTTLED | %s %s $%.2f | %s",
                        effective_request.side.upper(), effective_request.symbol,
                        effective_request.size_usd, throttle_reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        size_usd=effective_request.size_usd,
                        error=throttle_reason,
                        throttled=True,
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                return self._deny(effective_request, t_start, f"OrderFeasibility deny: throttler_error:{exc}")

        downstream_guard = getattr(self, "_downstream_guard", None)

        # ── Priority-3: Risk Governor ────────────────────────────────────
        if downstream_guard is not None:
            try:
                gov_ok, gov_reason, _ = downstream_guard.check_risk_governor(
                    symbol=effective_request.symbol,
                    proposed_risk_usd=effective_request.size_usd,
                    portfolio_value=effective_request.available_balance_usd or 0.0,
                )
                if not gov_ok:
                    logger.warning(
                        "ExecutionPipeline RISK_GOVERNOR | %s %s $%.2f | %s",
                        effective_request.side.upper(), effective_request.symbol,
                        effective_request.size_usd, gov_reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        size_usd=effective_request.size_usd,
                        error=f"RiskGovernor blocked: {gov_reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                return self._deny(effective_request, t_start, f"OrderFeasibility deny: risk_governor_error:{exc}")

        # ── Priority-4: Spread / Slippage Guard ──────────────────────────
        if downstream_guard is not None:
            try:
                _bid = float(
                    effective_request.bid_price_usd
                    if effective_request.bid_price_usd is not None
                    else (effective_request.price_hint_usd or 0.0)
                )
                _ask = float(
                    effective_request.ask_price_usd
                    if effective_request.ask_price_usd is not None
                    else (effective_request.price_hint_usd or 0.0)
                )
                slip_ok, slip_reason, _ = downstream_guard.check_slippage(
                    symbol=effective_request.symbol,
                    side=self._normalise_side(effective_request.side),
                    order_size_usd=effective_request.size_usd,
                    bid=_bid,
                    ask=_ask,
                    volume_24h_usd=float(effective_request.volume_24h_usd or 0.0),
                    volatility_pct=float(effective_request.volatility_pct or 0.02),
                )
                if not slip_ok:
                    logger.warning(
                        "ExecutionPipeline SLIPPAGE_BLOCKED | %s %s $%.2f | %s",
                        effective_request.side.upper(), effective_request.symbol,
                        effective_request.size_usd, slip_reason,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        size_usd=effective_request.size_usd,
                        error=f"SlippageGuard blocked: {slip_reason}",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                return self._deny(effective_request, t_start, f"PostGuard deny: slippage_error:{exc}")

        # ── Route to execution ───────────────────────────────────────────
        live_mode = os.getenv("LIVE_CAPITAL_VERIFIED", "").strip().lower() in {
            "1", "true", "yes", "enabled", "on"
        }
        fencing_token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
        _force_trade_active = (
            os.getenv("FORCE_TRADE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
            or os.getenv("FORCE_TRADE_MODE", "").strip().lower() in {"1", "true", "yes", "enabled", "on"}
        )
        if live_mode and not fencing_token:
            if _force_trade_active:
                logger.warning(
                    "[FORCE_TRADE] Bypassing fencing token requirement — "
                    "FORCE_TRADE_MODE=true overrides LIVE EXECUTION DISABLED gate. "
                    "symbol=%s side=%s size_usd=%.2f",
                    effective_request.symbol,
                    effective_request.side,
                    effective_request.size_usd,
                )
            else:
                raise RuntimeError(
                    "LIVE EXECUTION DISABLED: Missing fencing token"
                )

        if get_seak is not None:
            try:
                seak = get_seak()
                if bool(getattr(seak, "is_halted", False)):
                    halt_reason = str(getattr(seak, "_halt_reason", "") or "emergency halt")
                    self._emit_execution_rejection_telemetry(
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        reason=f"execution_authority_halt:{halt_reason}",
                    )
                    return PipelineResult(
                        success=False,
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        size_usd=effective_request.size_usd,
                        error=f"ExecutionAuthority reject: SEAK halted ({halt_reason})",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
            except Exception as exc:
                self._emit_execution_rejection_telemetry(
                    symbol=effective_request.symbol,
                    side=effective_request.side,
                    reason=f"execution_authority_halt_check:{exc}",
                )
                return PipelineResult(
                    success=False,
                    symbol=effective_request.symbol,
                    side=effective_request.side,
                    size_usd=effective_request.size_usd,
                    error=f"ExecutionAuthority reject: SEAK check failed ({exc})",
                    latency_ms=(time.monotonic() - t_start) * 1000,
                )

        try:
            authority_snapshot = runtime_authority_snapshot()
            if not bool(getattr(authority_snapshot, "ready", False)):
                if _force_trade_active:
                    logger.warning(
                        "[FORCE_TRADE] Bypassing runtime authority convergence check — "
                        "lifecycle_phase=%s coordinator_state=%s reason=%s. "
                        "symbol=%s side=%s size_usd=%.2f",
                        getattr(authority_snapshot, "lifecycle_phase", "unknown"),
                        getattr(authority_snapshot, "coordinator_state", "unknown"),
                        getattr(authority_snapshot, "reason", "unknown"),
                        effective_request.symbol,
                        effective_request.side,
                        effective_request.size_usd,
                    )
                else:
                    logger.error(
                        "🚫 [Pipeline] Runtime authority convergence lost | symbol=%s side=%s "
                        "lifecycle_phase=%s coordinator_state=%s reason=%s",
                        effective_request.symbol,
                        effective_request.side,
                        getattr(authority_snapshot, "lifecycle_phase", "unknown"),
                        getattr(authority_snapshot, "coordinator_state", "unknown"),
                        getattr(authority_snapshot, "reason", "unknown"),
                    )
                    return PipelineResult(
                        success=False,
                        symbol=effective_request.symbol,
                        side=effective_request.side,
                        size_usd=effective_request.size_usd,
                        error="Runtime authority convergence lost",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )
        except Exception as exc:
            if _force_trade_active:
                logger.warning(
                    "[FORCE_TRADE] Bypassing runtime authority snapshot error — %s. "
                    "symbol=%s side=%s size_usd=%.2f",
                    exc,
                    effective_request.symbol,
                    effective_request.side,
                    effective_request.size_usd,
                )
            else:
                return PipelineResult(
                    success=False,
                    symbol=effective_request.symbol,
                    side=effective_request.side,
                    size_usd=effective_request.size_usd,
                    error="Runtime authority convergence lost",
                    latency_ms=(time.monotonic() - t_start) * 1000,
                )
        except Exception as exc:
            return PipelineResult(
                success=False,
                symbol=effective_request.symbol,
                side=effective_request.side,
                size_usd=effective_request.size_usd,
                error=f"Runtime authority convergence lost: {exc}",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )

        try:
            with execution_authority_scope():
                # assert_execution_dispatch_permitted raises ExecutionBlocked on denial.
                # It is patchable in tests via bot.execution_pipeline.assert_execution_dispatch_permitted.
                # When FORCE_TRADE_MODE=true, bypass the authority dispatch gate so
                # orders can reach the exchange even when the lifecycle FSM has not
                # yet committed to LIVE_ACTIVE (e.g. missing Redis fencing token).
                if not _force_trade_active:
                    assert_execution_dispatch_permitted()
                else:
                    logger.info(
                        "[FORCE_TRADE] Bypassing assert_execution_dispatch_permitted — "
                        "FORCE_TRADE_MODE=true. symbol=%s side=%s size_usd=%.2f",
                        effective_request.symbol,
                        effective_request.side,
                        effective_request.size_usd,
                    )
                _correlation = get_runtime_correlation() or {}
                _intent_id = str(_correlation.get("intent_id") or "").strip()
                # ── Cycle integrity cross-check ───────────────────────────
                # Validate that the cycle_id in the correlation envelope matches
                # the cycle_id of the currently-active CycleSnapshot.  A mismatch
                # means execution was invoked with stale or misrouted correlation
                # state — log at WARNING so the drift is observable in the audit
                # trail.  This is a non-blocking diagnostic: execution continues
                # because the snapshot is advisory context (not a hard gate here)
                # and a mismatch may arise from valid async paths.
                _corr_cycle_id = str(_correlation.get("cycle_id") or "").strip()
                if _corr_cycle_id:
                    _active_snap = _get_pipeline_cycle_snapshot()
                    _snap_cycle_id = str(getattr(_active_snap, "cycle_id", "") or "").strip()
                    if _snap_cycle_id and _snap_cycle_id != _corr_cycle_id:
                        logger.warning(
                            "[Pipeline] cycle_id lineage drift: correlation cycle_id=%r "
                            "but active snapshot cycle_id=%r — execution proceeds but "
                            "journal lineage may be misaligned. symbol=%s side=%s",
                            _corr_cycle_id,
                            _snap_cycle_id,
                            effective_request.symbol,
                            effective_request.side,
                        )
                append_execution_journal_event(
                    event_type="order_submitted",
                    intent_id=_intent_id,
                    payload={
                        "symbol": effective_request.symbol,
                        "side": effective_request.side,
                        "size_usd": effective_request.size_usd,
                        "strategy": effective_request.strategy,
                        "account_id": effective_request.account_id,
                        "broker_hint": effective_request.preferred_broker or "",
                        "cycle_id": _corr_cycle_id,
                        "attempt_n": getattr(effective_request, "attempt_n", 0),
                    },
                )
                result = self._dispatch(effective_request, t_start)
        except ExecutionBlocked as exc:
            self._emit_execution_rejection_telemetry(
                symbol=effective_request.symbol,
                side=effective_request.side,
                reason=f"execution_authority_blocked:{exc}",
            )
            return PipelineResult(
                success=False,
                symbol=effective_request.symbol,
                side=effective_request.side,
                size_usd=effective_request.size_usd,
                error=f"ExecutionAuthority reject: {exc}",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )
        except Exception as exc:
            self._emit_execution_rejection_telemetry(
                symbol=effective_request.symbol,
                side=effective_request.side,
                reason=f"execution_authority_runtime:{exc}",
            )
            return PipelineResult(
                success=False,
                symbol=effective_request.symbol,
                side=effective_request.side,
                size_usd=effective_request.size_usd,
                error=f"ExecutionAuthority reject: {exc}",
                latency_ms=(time.monotonic() - t_start) * 1000,
            )



        _correlation = get_runtime_correlation() or {}
        _intent_id = str(_correlation.get("intent_id") or "").strip()
        if result.success:
            append_execution_journal_event(
                event_type="broker_ack",
                intent_id=_intent_id,
                payload={
                    "symbol": effective_request.symbol,
                    "side": effective_request.side,
                    "size_usd": effective_request.size_usd,
                    "broker": result.broker,
                    "fill_price": result.fill_price,
                    "filled_size_usd": result.filled_size_usd,
                    "latency_ms": result.latency_ms,
                    "attempt_n": getattr(effective_request, "attempt_n", 0),
                },
            )
            if getattr(self, "_margin_position_ledger", None) is not None:
                try:
                    self._margin_position_ledger.apply_ack_fill(effective_request, result)
                except Exception as exc:
                    logger.warning("ExecutionPipeline: margin ledger ack/fill update failed: %s", exc)

        if not result.success and self._is_retryable_exchange_rejection(result.error):
            logger.warning(
                "ExecutionPipeline: classifying exchange rejection as throttled | symbol=%s broker=%s error=%s",
                effective_request.symbol,
                effective_request.preferred_broker or "",
                result.error,
            )
            result.throttled = True

        if not result.success and not result.throttled:
            if getattr(self, "_margin_position_ledger", None) is not None:
                try:
                    self._margin_position_ledger.apply_reject_or_cancel(
                        effective_request,
                        result.error or "unknown exchange rejection",
                    )
                except Exception as exc:
                    logger.warning("ExecutionPipeline: margin ledger reject/cancel update failed: %s", exc)
            self._on_order_rejected(effective_request, result.error or "unknown exchange rejection")

        # Auto-register successful trades with the throttler
        if result.success and self._throttler is not None:
            try:
                self._throttler.record_trade(symbol=effective_request.symbol)
            except Exception as exc:
                logger.warning("ExecutionPipeline: throttler.record_trade failed: %s", exc)

        if self._pre_trade_risk_engine is not None:
            try:
                self._pre_trade_risk_engine.record_execution(
                    account_id=effective_request.account_id,
                    symbol=effective_request.symbol,
                    side=effective_request.side,
                    size_usd=effective_request.size_usd,
                    success=result.success,
                )
            except Exception as exc:
                logger.warning("ExecutionPipeline: pre-trade risk execution update failed: %s", exc)

        if self._execution_observer is not None:
            try:
                self._execution_observer.observe(
                    strategy=effective_request.strategy,
                    symbol=effective_request.symbol,
                    side=effective_request.side,
                    size_usd=effective_request.size_usd,
                    success=result.success,
                    error=result.error,
                )
            except Exception as exc:
                logger.warning("ExecutionPipeline: observer update failed: %s", exc)

        append_execution_journal_event(
            event_type="final_state",
            intent_id=_intent_id,
            payload={
                "symbol": effective_request.symbol,
                "side": effective_request.side,
                "size_usd": effective_request.size_usd,
                "success": result.success,
                "throttled": result.throttled,
                "error": result.error,
                "broker": result.broker,
                "latency_ms": result.latency_ms,
                "attempt_n": getattr(effective_request, "attempt_n", 0),
            },
        )
        return result

    def _on_order_rejected(self, request: PipelineRequest, error: str) -> None:
        """Handle a non-throttled, non-retryable order rejection.

        Soft blockers (auth, post-only, ACK timeout, slippage, balance,
        reconciliation, adapter exceptions) are classified and logged but
        do NOT raise SystemError — they return gracefully so the anomaly
        circuit breaker is not unnecessarily triggered.

        Hard rejections (order bypassed ECEL validation, unknown exchange
        error on an ECEL-validated order) still raise SystemError to
        trigger the anomaly circuit breaker.
        """
        self._emit_execution_rejection_telemetry(
            symbol=getattr(request, "symbol", "unknown"),
            side=getattr(request, "side", "unknown"),
            reason=error or "unknown exchange rejection",
        )

        # Classify the error before deciding whether to raise.
        blocker = BlockerType.UNKNOWN
        is_soft = False
        try:
            blocker = ExchangeErrorClassifier.classify(error)
            is_soft = ExchangeErrorClassifier.is_soft_blocker(blocker)
        except Exception:
            pass

        if is_soft:
            logger.warning(
                "🟡 EXCHANGE SOFT-REJECT [%s] | symbol=%s error=%s",
                blocker.value,
                getattr(request, "symbol", "unknown"),
                error,
            )
            # Soft blockers return without raising; the PipelineResult.success=False
            # already signals the caller that the order did not fill.
            return

        # Hard reject: ECEL-validated order still rejected by exchange.
        # This indicates a bug or a contract-rule gap that must be fixed.
        logger.critical("🚨 EXCHANGE HARD-REJECT [%s]: %s", blocker.value, error)
        raise SystemError("ECEL FAILURE — INVALID ORDER ESCAPED")

    def _emit_execution_rejection_telemetry(self, *, symbol: str, side: str, reason: str) -> None:
        if get_exchange_kill_switch_protector is None:
            return
        try:
            _eks = get_exchange_kill_switch_protector()
            _oid = f"exec-reject:pipeline:{symbol}:{side}:{int(time.time() * 1000)}"
            _eks.record_order_result(order_id=_oid, accepted=False)
        except Exception:
            pass

    def _log_ecel_final_order(self, request: PipelineRequest, compiled: Any) -> None:
        if compiled is None or not getattr(compiled, "accepted", False):
            return

        rule = getattr(compiled, "rule", None)
        if rule is None:
            return

        size = float(getattr(compiled, "compiled_base_size", 0.0) or 0.0)
        price = float(getattr(compiled, "compiled_price_usd", 0.0) or 0.0)
        notional = float(getattr(compiled, "compiled_notional_usd", 0.0) or 0.0)
        balance = float(request.available_balance_usd or 0.0)

        step = float(getattr(rule, "base_step_size", 0.0) or 0.0)
        min_qty = float(getattr(rule, "min_base_size", 0.0) or 0.0)
        min_notional = float(getattr(rule, "min_notional_usd", 0.0) or 0.0)

        step_valid = True
        if step > 0:
            step_valid = (Decimal(str(size)) % Decimal(str(step))) == Decimal("0")

        min_qty_valid = size >= min_qty
        notional_valid = notional >= min_notional
        funds_valid = True if request.available_balance_usd is None else notional <= balance

        logger.critical(
            "\n🧠 ECEL FINAL ORDER\n"
            "Symbol: %s\n"
            "Side: %s\n"
            "Price: %s\n"
            "Size: %s\n"
            "Notional: %s\n\n"
            "Constraints:\n"
            "  min_qty=%s\n"
            "  step_size=%s\n"
            "  min_notional=%s\n\n"
            "Balance:\n"
            "  available=%s\n\n"
            "Validation:\n"
            "  step_valid=%s\n"
            "  min_qty_valid=%s\n"
            "  notional_valid=%s\n"
            "  funds_valid=%s\n",
            request.symbol,
            request.side,
            price,
            size,
            notional,
            min_qty,
            step,
            min_notional,
            request.available_balance_usd,
            step_valid,
            min_qty_valid,
            notional_valid,
            funds_valid,
        )

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
        margin_ledger = getattr(self, "_margin_position_ledger", None)
        if margin_ledger is not None:
            try:
                margin_ledger.stop_periodic_reconcile()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch(self, request: PipelineRequest, t_start: float) -> PipelineResult:
        """Try MultiBrokerExecutionRouter, then fall back to ExecutionRouter.

        The call to each router is wrapped in an ACK-timeout guard: if the
        broker does not respond within ``NIJA_ACK_TIMEOUT_S`` seconds the
        dispatch is aborted and a soft ACK_TIMEOUT rejection is returned.
        The caller must reconcile open-order state before retrying.
        """

        if self._ecel_required:
            assert request.validated is True, "FATAL: Order bypassed ECEL"

        timeout_s = max(1.0, self._ack_timeout_s)

        def _run_with_ack_timeout(fn, *args, **kwargs) -> PipelineResult:
            """Execute *fn* in a thread, returning a timeout PipelineResult on expiry."""
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(fn, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_s)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        "ExecutionPipeline: ACK timeout after %.0fs | symbol=%s",
                        timeout_s,
                        request.symbol,
                    )
                    return PipelineResult(
                        success=False,
                        symbol=request.symbol,
                        side=request.side,
                        size_usd=request.size_usd,
                        error=f"ack_timeout: broker did not respond within {timeout_s:.0f}s",
                        latency_ms=(time.monotonic() - t_start) * 1000,
                    )

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
                        size_usd=float(request.size_usd or 0.0),
                        asset_class=request.asset_class or "",
                        order_type=(request.order_type or "market"),
                        limit_price=getattr(request, "limit_price", None),
                        preferred_broker=request.preferred_broker or "",
                        account_id=getattr(request, "account_id", "default"),
                        subaccount_id=getattr(request, "subaccount_id", None),
                        time_in_force=getattr(request, "time_in_force", None),
                        buying_power_usd=getattr(request, "buying_power_usd", None),
                        available_balance_usd=getattr(request, "available_balance_usd", None),
                        leverage=getattr(request, "leverage", None),
                        reduce_only=getattr(request, "reduce_only", None),
                        margin_mode=getattr(request, "margin_mode", None),
                        short_sell=getattr(request, "short_sell", None),
                        extended_hours=getattr(request, "extended_hours", None),
                        metadata={
                            **dict(getattr(request, "metadata", {}) or {}),
                            "request_id": getattr(request, "request_id", ""),
                            "intent_id": getattr(request, "intent_id", None),
                            "cycle_id": getattr(request, "cycle_id", None),
                            "sizing_mode": getattr(request, "sizing_mode", None),
                            "notional_usd": getattr(request, "notional_usd", None),
                            "units": getattr(request, "units", None),
                            "unit_type": getattr(request, "unit_type", None),
                            "price_hint_usd": (
                                getattr(request, "price_hint_usd", None)
                                if getattr(request, "price_hint_usd", None) is not None
                                else dict(getattr(request, "metadata", {}) or {}).get("price_hint_usd")
                            ),
                            "stop_price": getattr(request, "stop_price", None),
                            "instrument_type": request.instrument_type or "",
                            "quantity_mode": request.quantity_mode,
                            "shares": request.shares,
                            "contracts": request.contracts,
                            "account_type": request.account_type,
                            "leverage": request.leverage,
                            "reduce_only": request.reduce_only,
                            "position_effect": request.position_effect,
                            "borrow_intent": request.borrow_intent,
                            "margin_mode": request.margin_mode,
                            "time_in_force": request.time_in_force,
                            "extended_hours": request.extended_hours,
                            "strategy_metadata": dict(request.strategy_metadata or {}),
                        },
                    )

                    def _do_multi_route():
                        res = self._multi_router.route(route_req)
                        return PipelineResult(
                            success=res.success,
                            symbol=request.symbol,
                            side=request.side,
                            size_usd=request.size_usd,
                            fill_price=getattr(res, "fill_price", 0.0),
                            filled_size_usd=getattr(res, "filled_size_usd", 0.0),
                            broker=getattr(res, "broker", ""),
                            latency_ms=(time.monotonic() - t_start) * 1000,
                            error=getattr(res, "error", "") or "",
                        )

                    return _run_with_ack_timeout(_do_multi_route)
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
                        size_usd=float(request.size_usd or 0.0),
                        order_type=request.order_type,
                        metadata={
                            **dict(getattr(request, "metadata", {}) or {}),
                            "request_id": getattr(request, "request_id", ""),
                            "intent_id": getattr(request, "intent_id", None),
                            "cycle_id": getattr(request, "cycle_id", None),
                            "asset_class": getattr(request, "asset_class", None),
                            "account_id": getattr(request, "account_id", "default"),
                            "subaccount_id": getattr(request, "subaccount_id", None),
                            "time_in_force": getattr(request, "time_in_force", None),
                            "limit_price": getattr(request, "limit_price", None),
                            "stop_price": getattr(request, "stop_price", None),
                            "sizing_mode": getattr(request, "sizing_mode", None),
                            "notional_usd": getattr(request, "notional_usd", None),
                            "units": getattr(request, "units", None),
                            "unit_type": getattr(request, "unit_type", None),
                            "price_hint_usd": (
                                getattr(request, "price_hint_usd", None)
                                if getattr(request, "price_hint_usd", None) is not None
                                else dict(getattr(request, "metadata", {}) or {}).get("price_hint_usd")
                            ),
                            "leverage": getattr(request, "leverage", None),
                            "reduce_only": getattr(request, "reduce_only", None),
                            "margin_mode": getattr(request, "margin_mode", None),
                            "short_sell": getattr(request, "short_sell", None),
                            "extended_hours": getattr(request, "extended_hours", None),
                            "buying_power_usd": getattr(request, "buying_power_usd", None),
                            "available_balance_usd": getattr(request, "available_balance_usd", None),
                        },
                    )

                    def _do_single_route():
                        res = self._router.execute(order_req)
                        return PipelineResult(
                            success=res.success,
                            symbol=request.symbol,
                            side=request.side,
                            size_usd=request.size_usd,
                            fill_price=getattr(res, "fill_price", 0.0),
                            filled_size_usd=getattr(res, "filled_size_usd", 0.0),
                            latency_ms=(time.monotonic() - t_start) * 1000,
                            error=getattr(res, "error", "") or "",
                        )

                    return _run_with_ack_timeout(_do_single_route)
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
    def _is_retryable_exchange_rejection(error: str) -> bool:
        if not error:
            return False
        error_lower = error.lower()
        return any(keyword in error_lower for keyword in _RETRYABLE_EXCHANGE_ERROR_KEYWORDS)

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

    @staticmethod
    def _load_margin_health_gate():
        if MarginHealthGate is None:
            return None
        try:
            return MarginHealthGate()
        except Exception:
            return None

    @staticmethod
    def _load_pre_trade_risk_engine():
        for mod_name in ("bot.pre_trade_risk_engine", "pre_trade_risk_engine"):
            try:
                mod = __import__(mod_name, fromlist=["get_pre_trade_risk_engine"])
                engine = mod.get_pre_trade_risk_engine()
                logger.info("ExecutionPipeline: PreTradeRiskEngine loaded from %s", mod_name)
                return engine
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load pre-trade risk engine %s: %s", mod_name, exc)
        return None

    @staticmethod
    def _load_exchange_normalizer():
        for mod_name in ("bot.exchange_normalizer", "exchange_normalizer"):
            try:
                mod = __import__(mod_name, fromlist=["get_exchange_normalizer"])
                normalizer = mod.get_exchange_normalizer()
                logger.info("ExecutionPipeline: ExchangeNormalizer loaded from %s", mod_name)
                return normalizer
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load exchange normalizer %s: %s", mod_name, exc)
        return None

    @staticmethod
    def _load_allocation_clamp():
        for mod_name in ("bot.allocation_clamp", "allocation_clamp"):
            try:
                mod = __import__(mod_name, fromlist=["get_allocation_clamp"])
                clamp = mod.get_allocation_clamp()
                logger.info("ExecutionPipeline: AllocationClamp loaded from %s", mod_name)
                return clamp
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load allocation clamp %s: %s", mod_name, exc)
        return None

    @staticmethod
    def _load_execution_observer():
        for mod_name in ("bot.execution_observer", "execution_observer"):
            try:
                mod = __import__(mod_name, fromlist=["get_execution_observer"])
                observer = mod.get_execution_observer()
                logger.info("ExecutionPipeline: ExecutionObserver loaded from %s", mod_name)
                return observer
            except Exception as exc:
                logger.debug("ExecutionPipeline: could not load execution observer %s: %s", mod_name, exc)
        return None

    @staticmethod
    def _load_margin_position_ledger():
        if get_margin_position_ledger is None:
            return None
        try:
            return get_margin_position_ledger()
        except Exception as exc:
            logger.warning("ExecutionPipeline: margin position ledger unavailable: %s", exc)
            return None

    @staticmethod
    def _load_broker_capability_registry():
        if get_broker_capability_registry is None:
            return None
        try:
            return get_broker_capability_registry()
        except Exception as exc:
            logger.warning("ExecutionPipeline: broker capability registry unavailable: %s", exc)
            return None

    def _gate_broker_capabilities(
        self,
        request: PipelineRequest,
        t_start: float,
    ) -> Optional[PipelineResult]:
        registry = getattr(self, "_broker_capability_registry", None)
        if registry is None:
            return None
        try:
            allowed, reason = registry.validate_pre_dispatch(request)
            if not allowed:
                return self._deny(request, t_start, f"BrokerCapability deny: {reason}")
        except Exception as exc:
            return self._deny(request, t_start, f"BrokerCapability deny: registry_error:{exc}")
        return None

    def _start_margin_position_sync_loop(self) -> None:
        margin_ledger = getattr(self, "_margin_position_ledger", None)
        if margin_ledger is None:
            return
        poll_fn = None
        if self._multi_router is not None and callable(getattr(self._multi_router, "get_margin_position_snapshots", None)):
            poll_fn = self._multi_router.get_margin_position_snapshots
        elif self._router is not None and callable(getattr(self._router, "get_margin_position_snapshots", None)):
            poll_fn = self._router.get_margin_position_snapshots
        if poll_fn is None:
            return
        try:
            interval_s = float(os.getenv("NIJA_MARGIN_LEDGER_SYNC_INTERVAL_S", "30"))
            margin_ledger.start_periodic_reconcile(poll_fn, interval_s=interval_s)
        except Exception as exc:
            logger.warning("ExecutionPipeline: margin position sync loop unavailable: %s", exc)

    @staticmethod
    def _load_downstream_guard():
        try:
            guard = get_downstream_blocker_guard()
            logger.info("ExecutionPipeline: DownstreamBlockerGuard loaded")
            return guard
        except Exception as exc:
            logger.warning("ExecutionPipeline: DownstreamBlockerGuard unavailable: %s", exc)
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
        cycle_id = signal.get("cycle_id")
        if not cycle_id:
            # No canonical cycle_id provided — use a synthetic fallback so
            # reconciliation can still run, but warn so this lineage gap is
            # visible in the audit trail.  Callers should inject a real cycle_id
            # (from the runtime correlation or NijaCoreLoop) into the signal dict.
            cycle_id = f"pipeline-{self._run_count}"
            logger.warning(
                "[Pipeline] cycle_id missing from signal — using synthetic fallback %r. "
                "Fill reconciliation will not be traceable to a canonical cycle. "
                "Inject cycle_id into the signal dict to maintain full lineage.",
                cycle_id,
            )
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
            logger.critical("LIFECYCLE: entering execution coordinator")
            logger.info("[Pipeline] singleton created — full execution pipeline ENABLED")
    return _PIPELINE
