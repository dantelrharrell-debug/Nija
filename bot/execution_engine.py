# execution_engine.py
"""
NIJA Execution Engine
Handles order execution and position management for Apex Strategy v7.1

Enhanced with Execution Intelligence Layer for optimal trade execution.
"""

from typing import Any, Dict, Optional, List, Set, Tuple, cast
from datetime import datetime, timedelta
import logging
import sys
import os
import threading
import time as _time
from collections import defaultdict, deque

logger = logging.getLogger("nija.execution")

try:
    from bot.execution_pipeline import get_execution_pipeline, PipelineRequest
except ImportError:
    try:
        from execution_pipeline import get_execution_pipeline, PipelineRequest
    except ImportError:
        get_execution_pipeline = None  # type: ignore
        PipelineRequest = None         # type: ignore

try:
    from bot.execution_venue_config import get_preferred_execution_venue
except ImportError:
    try:
        from execution_venue_config import get_preferred_execution_venue
    except ImportError:
        get_preferred_execution_venue = None  # type: ignore[assignment]

try:
    from bot.broker_identity import resolve_broker_label, format_broker_identity
except ImportError:
    try:
        from broker_identity import resolve_broker_label, format_broker_identity  # type: ignore[import]
    except ImportError:
        def resolve_broker_label(broker: Any) -> str:  # type: ignore[misc]
            return type(broker).__name__.strip().lower() if broker is not None else "unknown"

        def format_broker_identity(broker: Any) -> str:  # type: ignore[misc]
            return resolve_broker_label(broker)

# ── ECEL: mandatory pre-trade choke point ─────────────────────────────────────
try:
    from bot.ecel_execution_compiler import (
        get_ecel_execution_compiler as _get_ecel,
        CompileRequest as _ECELCompileRequest,
    )
    _ECEL_AVAILABLE = True
    logger.info("✅ ECEL execution compiler loaded — mandatory pre-trade choke point active")
except ImportError:
    try:
        from ecel_execution_compiler import (
            get_ecel_execution_compiler as _get_ecel,
            CompileRequest as _ECELCompileRequest,
        )
        _ECEL_AVAILABLE = True
        logger.info("✅ ECEL execution compiler loaded — mandatory pre-trade choke point active")
    except ImportError:
        _ECEL_AVAILABLE = False
        _get_ecel = None  # type: ignore
        _ECELCompileRequest = None  # type: ignore
        logger.warning("⚠️ ECEL execution compiler not available — limit orders will use legacy sizing")

# Import canonical ExecutionResult contract
try:
    from bot.execution_result import (
        ExecutionResult as _ExecResult,
        OrderStatus as _OrderStatus,
        log_execution_result as _log_exec_result,
    )
    _EXEC_RESULT_AVAILABLE = True
except ImportError:
    try:
        from execution_result import (
            ExecutionResult as _ExecResult,
            OrderStatus as _OrderStatus,
            log_execution_result as _log_exec_result,
        )
        _EXEC_RESULT_AVAILABLE = True
    except ImportError:
        _EXEC_RESULT_AVAILABLE = False
        _ExecResult = None  # type: ignore
        _OrderStatus = None  # type: ignore
        _log_exec_result = None  # type: ignore

# ── Kraken Error Taxonomy — authoritative error classification layer ───────
try:
    from bot.kraken_error_taxonomy import (
        classify_kraken_error as _classify_kraken_error,
        KrakenRetryPolicy as _KrakenRetryPolicy,
        KrakenErrorCategory as _KrakenErrorCategory,
    )
    _KRAKEN_TAXONOMY_AVAILABLE = True
except ImportError:
    try:
        from kraken_error_taxonomy import (  # type: ignore[import]
            classify_kraken_error as _classify_kraken_error,
            KrakenRetryPolicy as _KrakenRetryPolicy,
            KrakenErrorCategory as _KrakenErrorCategory,
        )
        _KRAKEN_TAXONOMY_AVAILABLE = True
    except ImportError:
        _KRAKEN_TAXONOMY_AVAILABLE = False
        _classify_kraken_error = None  # type: ignore[assignment]
        _KrakenRetryPolicy = None  # type: ignore[assignment,misc]
        _KrakenErrorCategory = None  # type: ignore[assignment,misc]

# ── Execution State Controller — state-machine driven order lifecycle ──────
try:
    from bot.execution_state_controller import (
        ExecutionStateController as _ExecutionStateController,
        ExecutionOrderState as _ExecutionOrderState,
    )
    _EXEC_STATE_CONTROLLER_AVAILABLE = True
except ImportError:
    try:
        from execution_state_controller import (  # type: ignore[import]
            ExecutionStateController as _ExecutionStateController,
            ExecutionOrderState as _ExecutionOrderState,
        )
        _EXEC_STATE_CONTROLLER_AVAILABLE = True
    except ImportError:
        _EXEC_STATE_CONTROLLER_AVAILABLE = False
        _ExecutionStateController = None  # type: ignore[assignment,misc]
        _ExecutionOrderState = None       # type: ignore[assignment,misc]

# Import Execution Intelligence Layer
try:
    from bot.execution_intelligence import (
        get_execution_intelligence,
        MarketMicrostructure,
        ExecutionIntelligence,
        ExecutionPlan,
        OrderType as EIOrderType
    )
    EXECUTION_INTELLIGENCE_AVAILABLE = True
    logger.info("✅ Execution Intelligence Layer loaded - Elite execution optimization active")
except ImportError:
    try:
        from execution_intelligence import (
            get_execution_intelligence,
            MarketMicrostructure,
            ExecutionIntelligence,
            ExecutionPlan,
            OrderType as EIOrderType
        )
        EXECUTION_INTELLIGENCE_AVAILABLE = True
        logger.info("✅ Execution Intelligence Layer loaded - Elite execution optimization active")
    except ImportError:
        EXECUTION_INTELLIGENCE_AVAILABLE = False
        logger.warning("⚠️ Execution Intelligence Layer not available - using basic execution")
        get_execution_intelligence = None
        MarketMicrostructure = None
        ExecutionIntelligence = None
        ExecutionPlan = None
        EIOrderType = None

# Import Minimum Notional Gate (Enhancement #1)
try:
    from bot.minimum_notional_gate import get_minimum_notional_gate, NotionalGateConfig
    MIN_NOTIONAL_GATE_AVAILABLE = True
    logger.info("✅ Minimum Notional Gate loaded - Entry size validation active")
except ImportError:
    try:
        from minimum_notional_gate import get_minimum_notional_gate, NotionalGateConfig
        MIN_NOTIONAL_GATE_AVAILABLE = True
        logger.info("✅ Minimum Notional Gate loaded - Entry size validation active")
    except ImportError:
        MIN_NOTIONAL_GATE_AVAILABLE = False
        logger.warning("⚠️ Minimum Notional Gate not available")

# Import BalanceService (single source of truth for balance snapshots)
try:
    from bot.balance_service import BalanceService
    BALANCE_SERVICE_AVAILABLE = True
except ImportError:
    try:
        from balance_service import BalanceService
        BALANCE_SERVICE_AVAILABLE = True
    except ImportError:
        BALANCE_SERVICE_AVAILABLE = False
        BalanceService = None  # type: ignore

# Import Execution Confirmation Layer (fill verification)
try:
    from bot.execution_confirmation_layer import get_execution_confirmation_layer, FillStatus
    EXECUTION_CONFIRMATION_AVAILABLE = True
except ImportError:
    try:
        from execution_confirmation_layer import get_execution_confirmation_layer, FillStatus
        EXECUTION_CONFIRMATION_AVAILABLE = True
    except ImportError:
        EXECUTION_CONFIRMATION_AVAILABLE = False
        get_execution_confirmation_layer = None  # type: ignore
        FillStatus = None  # type: ignore

try:
    from bot.signal_funnel_diagnostics import get_signal_funnel
    SIGNAL_FUNNEL_AVAILABLE = True
except ImportError:
    try:
        from signal_funnel_diagnostics import get_signal_funnel
        SIGNAL_FUNNEL_AVAILABLE = True
    except ImportError:
        SIGNAL_FUNNEL_AVAILABLE = False
        get_signal_funnel = None  # type: ignore

try:
    from bot.pipeline_funnel import get_pipeline_funnel as _get_pipeline_funnel
    _PIPELINE_FUNNEL_AVAILABLE = True
except ImportError:
    try:
        from pipeline_funnel import get_pipeline_funnel as _get_pipeline_funnel  # type: ignore[import]
        _PIPELINE_FUNNEL_AVAILABLE = True
    except ImportError:
        _PIPELINE_FUNNEL_AVAILABLE = False
        _get_pipeline_funnel = None  # type: ignore

# Import Exchange Constraints Enforcer (reject-proof order validation)
try:
    from bot.exchange_constraints_enforcer import (
        validate_order_constraints,
        calculate_fillable_order_size,
    )
    EXCHANGE_CONSTRAINTS_AVAILABLE = True
    logger.info("✅ Exchange Constraints Enforcer loaded - Reject-proof order sizing active")
except ImportError:
    try:
        from exchange_constraints_enforcer import (
            validate_order_constraints,
            calculate_fillable_order_size,
        )
        EXCHANGE_CONSTRAINTS_AVAILABLE = True
        logger.info("✅ Exchange Constraints Enforcer loaded - Reject-proof order sizing active")
    except ImportError:
        EXCHANGE_CONSTRAINTS_AVAILABLE = False
        logger.warning("⚠️ Exchange Constraints Enforcer not available")
        validate_order_constraints = None
        calculate_fillable_order_size = None

# Import Exchange Order Compiler (canonical order validation at final authority)
try:
    from bot.exchange_order_compiler import (
        ExchangeOrderCompiler,
        PricingSnapshot,
        OrderCompileError,
    )
    EXCHANGE_ORDER_COMPILER_AVAILABLE = True
    _eoc = ExchangeOrderCompiler()
    logger.info("✅ Exchange Order Compiler loaded - Final authority order validation active")
except ImportError:
    try:
        from exchange_order_compiler import (
            ExchangeOrderCompiler,
            PricingSnapshot,
            OrderCompileError,
        )
        EXCHANGE_ORDER_COMPILER_AVAILABLE = True
        _eoc = ExchangeOrderCompiler()
        logger.info("✅ Exchange Order Compiler loaded - Final authority order validation active")
    except ImportError:
        EXCHANGE_ORDER_COMPILER_AVAILABLE = False
        logger.warning("⚠️ Exchange Order Compiler not available")
        ExchangeOrderCompiler = None
        PricingSnapshot = None
        OrderCompileError = None
        _eoc = None
        get_minimum_notional_gate = None
        NotionalGateConfig = None

# Import hard controls for LIVE CAPITAL VERIFIED check
try:
    # Try standard import first (when running as package)
    from controls import get_hard_controls
    HARD_CONTROLS_AVAILABLE = True
    logger.info("✅ Hard controls module loaded for LIVE CAPITAL VERIFIED checks")
except ImportError:
    try:
        # Fallback: Add controls directory to path if needed
        controls_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'controls')
        if controls_path not in sys.path:
            sys.path.insert(0, controls_path)

        from controls import get_hard_controls
        HARD_CONTROLS_AVAILABLE = True
        logger.info("✅ Hard controls module loaded for LIVE CAPITAL VERIFIED checks")
    except ImportError as e:
        HARD_CONTROLS_AVAILABLE = False
        logger.warning(f"⚠️ Hard controls not available: {e}")
        logger.warning("   LIVE CAPITAL VERIFIED check will be skipped")
        get_hard_controls = None

# Constants
VALID_ORDER_STATUSES = ['open', 'closed', 'filled', 'pending']
LOG_SEPARATOR = "=" * 70

# ─── Net Edge Gate ────────────────────────────────────────────────────────────
# Minimum net profit (as a decimal fraction of position size) that a trade must
# clear AFTER fees, slippage, and spread before execution is allowed.
# Example: 0.0035 = 0.35% – every trade must earn at least 0.35% net or be
# rejected. This ensures NIJA never takes trades that are unprofitable by design.
MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.0035"))  # 0.35% default

# ─── FIX 1: Minimum account balance gate ────────────────────────────────────
# Accounts below this USD balance are skipped entirely — no fake executions.
# Lowered to $50 to allow trading with ~$174 balance (micro-cap / HF scalp mode).
MINIMUM_TRADING_BALANCE: float = float(os.getenv("MINIMUM_TRADING_BALANCE", "50.0"))

# ─── FIX 2: Minimum notional order size ─────────────────────────────────────
# Hard floor for every order regardless of broker-specific minimums.
# Lowered to $10 for micro-cap / HF scalp mode with $174 balance.
MIN_TRADE_USD: float = float(os.getenv("MIN_TRADE_USD", os.getenv("MIN_NOTIONAL_USD", "10.0")))
MIN_NOTIONAL_USD: float = MIN_TRADE_USD
# Exchange-level hard floor; acts as an absolute minimum before broker-specific
# or exchange-specific constraints apply.
EXCHANGE_HARD_FLOOR_USD: float = 1.0
# Synthetic order ids emitted by ExecutionPipeline (no broker order to confirm).
# These are internal/simulated ids that do not map to a real exchange order_id.
SYNTHETIC_ORDER_IDS: Set[str] = {"pipeline"}
LARGE_QUANTITY_RATIO_THRESHOLD: float = 1e6
MIN_POSITION_SIZE_EPSILON: float = 1e-9

# Fee-dominated micro-trade guardrails.
TAKER_FEE_RATE: float = float(os.getenv("TAKER_FEE_RATE", "0.0026"))
MIN_EDGE_MULTIPLIER: float = float(os.getenv("MIN_EDGE_MULTIPLIER", "1.5"))

# Keep a cash reserve so rounding/fees don't trigger false insufficient-funds rejects.
BALANCE_BUFFER_PCT: float = float(os.getenv("BALANCE_BUFFER_PCT", "0.10"))

# One-shot probe controls for end-to-end execution validation.
FORCE_FIRST_TRADE: bool = os.getenv("FORCE_FIRST_TRADE", "false").lower() in ("1", "true", "yes", "enabled")
FORCE_TRADE_NOTIONAL: float = float(os.getenv("FORCE_TRADE_NOTIONAL", "10.0"))
FORCE_TRADE_ON_FIRST_VALID_SIGNAL: bool = os.getenv(
    "FORCE_TRADE_ON_FIRST_VALID_SIGNAL", "false"
).lower() in ("1", "true", "yes", "enabled")

# ─── FIX 4: Live mode enforcement ───────────────────────────────────────────
LIVE_CAPITAL_VERIFIED: bool = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower() == "true"
DRY_RUN_MODE: bool = os.getenv("DRY_RUN_MODE", "false").lower() == "true"

# ── Small account / small order flags (Apr 2026) ────────────────────────────
# Allow trading with small account balances (~$174) and small order sizes (~$10).
# Both default to True to enable HF scalp mode with limited capital.
ALLOW_SMALL_ORDERS: bool = os.getenv("ALLOW_SMALL_ORDERS", "true").lower() in ("1", "true", "yes", "on")
ALLOW_SMALL_ACCOUNT_TRADING: bool = os.getenv("ALLOW_SMALL_ACCOUNT_TRADING", "true").lower() in ("1", "true", "yes", "on")

# ─── FIX 5: Force trade mode — bypasses all signal filters to confirm pipeline
# Supports both FORCE_TRADE and FORCE_TRADE_MODE for compatibility.
# FORCE_TRADE bypasses expectancy/edge/regime gates — keep false in production
# to avoid rapid order spam that triggers exchange rate limiting.
FORCE_TRADE_MODE: bool = (
    os.getenv("FORCE_TRADE", "false").lower() == "true"
    or os.getenv("FORCE_TRADE_MODE", "false").lower() == "true"
)

# Positive expectancy gate (true E>0 model)
# E = p(win)*net_win - (1-p(win))*net_loss must be > threshold.
# Default win probability can be overridden with EXPECTED_WIN_RATE_PCT.
DEFAULT_EXPECTED_WIN_RATE: float = 0.50
MIN_EXPECTANCY_THRESHOLD_PCT: float = 0.0

# Edge-score / regime / market-quality / Kelly-lite controls
MIN_EDGE_SCORE_THRESHOLD: float = float(os.getenv("MIN_EDGE_SCORE_THRESHOLD", "0.0"))
MARKET_QUALITY_THRESHOLD: float = float(os.getenv("MARKET_QUALITY_THRESHOLD", "0.40"))
MIN_TP_PCT: float = float(os.getenv("MIN_TP_PCT", "0.008"))
MAX_SL_PCT: float = float(os.getenv("MAX_SL_PCT", "0.030"))
MAX_KELLY_FRACTION: float = float(os.getenv("MAX_KELLY_FRACTION", "0.25"))
PAIR_EXPECTANCY_WINDOW: int = int(os.getenv("PAIR_EXPECTANCY_WINDOW", "100"))
PAIR_EXPECTANCY_MIN_TRADES: int = int(os.getenv("PAIR_EXPECTANCY_MIN_TRADES", "50"))
EXPECTANCY_DISABLE_COOLDOWN_MINUTES: int = int(os.getenv("EXPECTANCY_DISABLE_COOLDOWN_MINUTES", "240"))


def calculate_net_edge(
    entry: float,
    target: float,
    size: float,
    fee_rate: float,
    slippage_rate: float,
    spread_rate: float,
) -> float:
    """Calculate the net profit of a prospective trade after all costs.

    Args:
        entry:         Expected entry price.
        target:        Expected exit / take-profit price.
        size:          Position size in USD (notional).
        fee_rate:      One-way fee rate as a decimal (e.g. 0.006 for 0.6%).
                       Applied twice (entry + exit).
        slippage_rate: Expected slippage as a decimal (e.g. 0.001 for 0.1%).
        spread_rate:   Bid-ask spread as a decimal (e.g. 0.001 for 0.1%).

    Returns:
        Net profit in USD. Negative means the trade would be a net loss even
        if the price target is hit.
    """
    if entry <= 0 or target <= 0 or size <= 0:
        return 0.0

    gross_profit = (target - entry) * size / entry  # USD gross profit
    fees = size * fee_rate * 2        # round-trip fees (entry + exit)
    slippage = size * slippage_rate   # one-way slippage
    spread = size * spread_rate       # spread cost on entry

    net_profit = gross_profit - fees - slippage - spread
    return net_profit


def trade_is_economical(
    notional_usd: float,
    expected_edge_pct: float,
    fee_rate: float = TAKER_FEE_RATE,
    min_edge_multiplier: float = MIN_EDGE_MULTIPLIER,
) -> bool:
    """Return True when expected gross edge is meaningfully above fee drag."""
    if notional_usd <= 0.0 or expected_edge_pct <= 0.0:
        return False
    fees = notional_usd * max(0.0, fee_rate)
    expected_profit = notional_usd * expected_edge_pct
    return expected_profit >= (fees * max(1.0, min_edge_multiplier))

# Import fee-aware configuration for profit calculations
try:
    from fee_aware_config import MARKET_ORDER_ROUND_TRIP
    FEE_AWARE_MODE = True
    # Use market order fees as conservative estimate (worst case)
    DEFAULT_ROUND_TRIP_FEE = MARKET_ORDER_ROUND_TRIP  # 1.4%
    logger.info(f"✅ Fee-aware profit calculations enabled (round-trip fee: {DEFAULT_ROUND_TRIP_FEE*100:.1f}%)")
except ImportError:
    FEE_AWARE_MODE = False
    DEFAULT_ROUND_TRIP_FEE = 0.014  # 1.4% default
    logger.warning(f"⚠️ Fee-aware config not found - using default {DEFAULT_ROUND_TRIP_FEE*100:.1f}% round-trip fee")

# Import trade ledger database
try:
    from trade_ledger_db import get_trade_ledger_db
    TRADE_LEDGER_ENABLED = True
    logger.info("✅ Trade ledger database enabled")
except ImportError:
    TRADE_LEDGER_ENABLED = False
    logger.warning("⚠️ Trade ledger database not available")
    get_trade_ledger_db = None  # type: ignore

# Import Recovery Controller for capital-first safety (NEW - Feb 2026)
try:
    from bot.recovery_controller import get_recovery_controller
    RECOVERY_CONTROLLER_AVAILABLE = True
    logger.info("✅ Recovery Controller loaded - Capital-first safety layer active")
except ImportError:
    try:
        from recovery_controller import get_recovery_controller
        RECOVERY_CONTROLLER_AVAILABLE = True
        logger.info("✅ Recovery Controller loaded - Capital-first safety layer active")
    except ImportError:
        RECOVERY_CONTROLLER_AVAILABLE = False
        logger.warning("⚠️ Recovery Controller not available - safety layer disabled")
        get_recovery_controller = None

# Import Capital CSM v2 for proof-of-trade forced sizing
try:
    from bot.capital_csm_v2 import get_csm_v2
    CAPITAL_CSM_V2_AVAILABLE = True
    logger.info("✅ Capital CSM v2 loaded - proof-of-trade forced sizing active")
except ImportError:
    try:
        from capital_csm_v2 import get_csm_v2
        CAPITAL_CSM_V2_AVAILABLE = True
        logger.info("✅ Capital CSM v2 loaded - proof-of-trade forced sizing active")
    except ImportError:
        CAPITAL_CSM_V2_AVAILABLE = False
        logger.warning("⚠️ Capital CSM v2 not available - proof-of-trade sizing disabled")
        get_csm_v2 = None

# Import custom exceptions for safety checks
try:
    import bot.exceptions as _exc_mod
except ImportError:
    try:
        import exceptions as _exc_mod
    except ImportError:
        _exc_mod = None

if _exc_mod is not None:
    ExecutionError = cast(Any, _exc_mod.ExecutionError)
    BrokerMismatchError = cast(Any, _exc_mod.BrokerMismatchError)
    InvalidTxidError = cast(Any, _exc_mod.InvalidTxidError)
    InvalidFillPriceError = cast(Any, _exc_mod.InvalidFillPriceError)
    OrderRejectedError = cast(Any, _exc_mod.OrderRejectedError)
    CapitalIntegrityError = cast(Any, _exc_mod.CapitalIntegrityError)
else:
    # Fallback: Define locally if import fails
        class ExecutionError(Exception):
            pass
        class BrokerMismatchError(ExecutionError):
            pass
        class InvalidTxidError(ExecutionError):
            pass
        class InvalidFillPriceError(ExecutionError):
            pass
        class OrderRejectedError(ExecutionError):
            pass
        class CapitalIntegrityError(Exception):
            pass

# Import ActiveCapital for execution gating (FIX 4)
try:
    from bot.capital.active_capital import get_active_capital
    ACTIVE_CAPITAL_AVAILABLE = True
    logger.info("✅ ActiveCapital loaded — execution capital gate active")
except ImportError:
    try:
        from capital.active_capital import get_active_capital  # type: ignore
        ACTIVE_CAPITAL_AVAILABLE = True
        logger.info("✅ ActiveCapital loaded — execution capital gate active")
    except ImportError:
        ACTIVE_CAPITAL_AVAILABLE = False
        get_active_capital = None  # type: ignore
        logger.warning("⚠️ ActiveCapital not available — capital gate disabled")

# Import restriction manager for geographic restriction handling
try:
    from bot.restricted_symbols import (
        add_restricted_symbol as _add_restricted_symbol_impl,
        is_geographic_restriction_error as _is_geo_restriction_error_impl,
    )
    RESTRICTION_MANAGER_AVAILABLE = True
except ImportError:
    try:
        from restricted_symbols import (
            add_restricted_symbol as _add_restricted_symbol_impl,
            is_geographic_restriction_error as _is_geo_restriction_error_impl,
        )
        RESTRICTION_MANAGER_AVAILABLE = True
    except ImportError:
        RESTRICTION_MANAGER_AVAILABLE = False
        _add_restricted_symbol_impl = None
        _is_geo_restriction_error_impl = None


def add_restricted_symbol(symbol: str, reason: Optional[str] = None) -> None:
    if callable(_add_restricted_symbol_impl):
        _add_restricted_symbol_impl(symbol, reason or "")


def is_geographic_restriction_error(error_message: str) -> bool:
    if callable(_is_geo_restriction_error_impl):
        return bool(_is_geo_restriction_error_impl(error_message))
    return False

# Import profit confirmation feature flag and logger
try:
    from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
    logger.info("✅ Profit confirmation feature flag loaded")
except ImportError:
    PROFIT_CONFIRMATION_AVAILABLE = False
    logger.warning("⚠️ Profit confirmation feature flag not available - feature disabled")

try:
    from bot.profit_confirmation_logger import ProfitConfirmationLogger
    PROFIT_LOGGER_AVAILABLE = True
    logger.info("✅ Profit Confirmation Logger available")
except ImportError:
    try:
        from profit_confirmation_logger import ProfitConfirmationLogger
        PROFIT_LOGGER_AVAILABLE = True
        logger.info("✅ Profit Confirmation Logger available")
    except ImportError:
        PROFIT_LOGGER_AVAILABLE = False
        logger.warning("⚠️ Profit Confirmation Logger not available - profit tracking disabled")
        ProfitConfirmationLogger = None

# ── Performance Tracker — fees + slippage aware closed-trade recording ────────
try:
    from bot.performance_tracker import get_performance_tracker as _get_perf_tracker
    PERFORMANCE_TRACKER_AVAILABLE = True
    logger.info("✅ Performance Tracker loaded — fee/slippage-aware trade recording active")
except ImportError:
    try:
        from performance_tracker import get_performance_tracker as _get_perf_tracker
        PERFORMANCE_TRACKER_AVAILABLE = True
        logger.info("✅ Performance Tracker loaded — fee/slippage-aware trade recording active")
    except ImportError:
        PERFORMANCE_TRACKER_AVAILABLE = False
        _get_perf_tracker = None  # type: ignore
        logger.warning("⚠️ Performance Tracker not available — closed-trade stats disabled")


class ExecutionEngine:
    """
    Manages order execution and position tracking
    Designed to be broker-agnostic and extensible
    """

    # CRITICAL: Maximum acceptable immediate loss on entry (as percentage)
    # If position shows loss greater than this immediately after fill, reject it
    # This prevents accepting trades with excessive spread/slippage
    # Threshold: 0.5% - This is set conservatively to catch truly bad fills
    # while still allowing for normal market microstructure (typical spread ~0.1-0.3%)
    # Coinbase taker fee is 0.6%, but we want to catch ADDITIONAL unfavorable slippage
    # beyond what's expected from the quote price. So 0.5% extra slippage = very bad fill
    MAX_IMMEDIATE_LOSS_PCT = 0.005  # 0.5%

    def __init__(self, broker_client=None, user_id: str = 'master'):
        """
        Initialize Execution Engine

        Args:
            broker_client: Broker client instance (Coinbase, Alpaca, Binance, etc.)
            user_id: User ID for trade tracking (default: 'master')
        """
        self.broker_client = broker_client
        self.user_id = user_id
        self.positions: Dict[str, Dict] = {}
        self.orders: List[Dict] = []
        self._force_first_trade_done = False

        # FIX #1: Atomic Position Close Lock - Prevent double-sells
        # When a sell is submitted, symbol is added to closing_positions
        # Only removed after confirmed rejection, failure, or final settlement
        self.closing_positions: Set[str] = set()
        self._closing_lock = threading.Lock()  # Protects closing_positions set

        # FIX #3: Block Concurrent Exit When Active Exit In Progress
        # Tracks symbols with active exit orders to prevent concurrent exit attempts
        self.active_exit_orders: Set[str] = set()
        self._exit_lock = threading.Lock()  # Protects active_exit_orders set

        # Track rejected trades for monitoring
        self.rejected_trades_count = 0
        self.immediate_exit_count = 0

        # Positive-expectancy runtime memory (pair-level health)
        self._pair_realized_expectancy = defaultdict(lambda: deque(maxlen=PAIR_EXPECTANCY_WINDOW))
        self._disabled_pairs: Set[str] = set()
        self._disabled_until: Dict[str, datetime] = {}
        _force_reenable_raw = os.getenv("EXPECTANCY_FORCE_ENABLE_BUCKETS", "")
        self._force_enable_buckets: Set[str] = {
            x.strip() for x in _force_reenable_raw.split(",") if x.strip()
        }

        # Initialize trade ledger database
        _trade_ledger_factory = globals().get("get_trade_ledger_db")
        if TRADE_LEDGER_ENABLED and callable(_trade_ledger_factory):
            try:
                self.trade_ledger = _trade_ledger_factory()
                logger.info("✅ Trade ledger database connected")
            except Exception as e:
                logger.warning(f"⚠️ Could not connect to trade ledger: {e}")
                self.trade_ledger = None
        else:
            self.trade_ledger = None

        # Initialize Execution Intelligence Layer
        if EXECUTION_INTELLIGENCE_AVAILABLE and callable(get_execution_intelligence):
            try:
                self.execution_intelligence = get_execution_intelligence()
                logger.info("✅ Execution Intelligence initialized - Elite optimization enabled")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Execution Intelligence: {e}")
                self.execution_intelligence = None
        else:
            self.execution_intelligence = None
        
        # Initialize Profit Confirmation Logger
        if PROFIT_CONFIRMATION_AVAILABLE and PROFIT_LOGGER_AVAILABLE and ProfitConfirmationLogger is not None:
            try:
                self.profit_logger = ProfitConfirmationLogger(data_dir="./data")
                logger.info("✅ Profit Confirmation Logger initialized - Enhanced profit tracking enabled")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Profit Confirmation Logger: {e}")
                self.profit_logger = None
        else:
            self.profit_logger = None

        # Execution State Controller — taxonomy-driven per-order lifecycle FSM.
        # Lazily instantiated on first use so the controller is always fresh
        # and its state does not leak across unrelated trade attempts.
        self._execution_controller: Optional[Any] = None

    def _apply_minimum_notional_gate(
        self,
        *,
        symbol: str,
        position_size: float,
        broker_name: Optional[str],
        balance_usd: float,
        affordable_usd: Optional[float],
    ) -> Tuple[Optional[float], Optional[str]]:
        """Return an executable size or a rejection reason after notional gating."""
        if not (MIN_NOTIONAL_GATE_AVAILABLE and get_minimum_notional_gate):
            return position_size, None

        notional_gate = get_minimum_notional_gate()
        is_valid, rejection_reason = notional_gate.validate_entry_size(
            symbol=symbol,
            size_usd=position_size,
            is_stop_loss=False,
            broker_name=broker_name,
            balance=balance_usd,
        )
        if is_valid:
            return position_size, None

        adjusted_size = float(
            notional_gate.adjust_size_to_minimum(
                position_size,
                broker_name=broker_name,
                balance=balance_usd,
            )
            or position_size
        )
        if adjusted_size > position_size and (affordable_usd is None or adjusted_size <= affordable_usd):
            logger.info(
                "📈 Auto-adjusting size from $%.2f to $%.2f (minimum notional gate)",
                position_size,
                adjusted_size,
            )
            return adjusted_size, None

        return None, rejection_reason

    def _submit_market_order_via_pipeline(
        self,
        broker_client,
        symbol: str,
        side: str,
        size_usd: float,
        available_balance_usd: Optional[float] = None,
        price_hint_usd: Optional[float] = None,
        strategy_name: str = "ExecutionEngine",
    ) -> Dict[str, Any]:
        """Canonical market-order submit through ExecutionPipeline/ECEL."""
        print(
            f"[NIJA-PRINT] _submit_market_order_via_pipeline CALLED | "
            f"symbol={symbol} side={side} size_usd={float(size_usd or 0.0):.2f} "
            f"price_hint={float(price_hint_usd or 0.0):.6f} "
            f"pipeline_available={get_execution_pipeline is not None and PipelineRequest is not None} "
            f"force_trade={os.getenv('FORCE_TRADE', 'false')}",
            flush=True,
        )
        logger.critical(
            "🔌 [BrokerAdapter] ORDER SUBMISSION STARTED | "
            "symbol=%s side=%s size_usd=%.2f price_hint=%.6f strategy=%s "
            "pipeline_available=%s force_trade=%s",
            symbol,
            side,
            float(size_usd or 0.0),
            float(price_hint_usd or 0.0),
            strategy_name,
            get_execution_pipeline is not None and PipelineRequest is not None,
            os.getenv("FORCE_TRADE", "false"),
        )
        if get_execution_pipeline is None or PipelineRequest is None:
            logger.critical(
                "🚫 [BrokerAdapter] ORDER DROPPED — ExecutionPipeline unavailable "
                "| symbol=%s side=%s size_usd=%.2f",
                symbol, side, float(size_usd or 0.0),
            )
            return {
                "status": "error",
                "error": "ExecutionPipeline unavailable",
                "symbol": symbol,
                "side": side,
            }

        preferred_broker = "coinbase"
        try:
            btype = getattr(broker_client, "broker_type", None)
            if btype is not None:
                if hasattr(btype, "value"):
                    preferred_broker = str(btype.value).lower()
                elif isinstance(btype, str) and btype.strip():
                    preferred_broker = btype.strip().lower()
            elif isinstance(getattr(broker_client, "NAME", None), str):
                name = str(getattr(broker_client, "NAME")).strip().lower()
                if "kraken" in name:
                    preferred_broker = "kraken"
                elif "coinbase" in name:
                    preferred_broker = "coinbase"
                elif "okx" in name:
                    preferred_broker = "okx"
                elif "binance" in name:
                    preferred_broker = "binance"
                elif "alpaca" in name:
                    preferred_broker = "alpaca"
        except Exception:
            pass

        # Honor explicit execution-venue preference in live incidents.
        _preferred_env = (
            get_preferred_execution_venue(os.environ)
            if get_preferred_execution_venue is not None
            else None
        )
        if _preferred_env is not None:
            preferred_broker = _preferred_env

        bid_price_usd: Optional[float] = None
        ask_price_usd: Optional[float] = None
        try:
            if hasattr(broker_client, "get_best_bid_ask"):
                ticker = broker_client.get_best_bid_ask(product_ids=[symbol])
                pricebooks = (ticker or {}).get("pricebooks", [{}])
                book = pricebooks[0] if pricebooks else {}
                bid_price_usd = float((book.get("bids") or [{}])[0].get("price", 0) or 0) or None
                ask_price_usd = float((book.get("asks") or [{}])[0].get("price", 0) or 0) or None
                if (price_hint_usd is None or price_hint_usd <= 0) and bid_price_usd and ask_price_usd:
                    price_hint_usd = (bid_price_usd + ask_price_usd) / 2.0
        except Exception:
            bid_price_usd = None
            ask_price_usd = None

        res = get_execution_pipeline().execute(
            PipelineRequest(
                strategy=strategy_name,
                symbol=symbol,
                side=side,
                size_usd=float(max(0.0, size_usd)),
                order_type="MARKET",
                preferred_broker=preferred_broker,
                available_balance_usd=available_balance_usd,
                price_hint_usd=price_hint_usd,
                bid_price_usd=bid_price_usd,
                ask_price_usd=ask_price_usd,
                metadata={
                    "broker_client": broker_client,
                    "broker_name": preferred_broker,
                    "price_hint_usd": price_hint_usd,
                },
            )
        )

        if not res.success:
            print(
                f"[NIJA-PRINT] ORDER REJECTED by ExecutionPipeline | "
                f"symbol={symbol} side={side} size_usd={float(size_usd or 0.0):.2f} "
                f"error={res.error or 'unknown'} "
                f"broker={getattr(res, 'broker', preferred_broker)}",
                flush=True,
            )
            logger.critical(
                "❌ [BrokerAdapter] ORDER REJECTED by ExecutionPipeline | "
                "symbol=%s side=%s size_usd=%.2f error=%s broker=%s",
                symbol, side, float(size_usd or 0.0),
                res.error or "unknown",
                getattr(res, "broker", preferred_broker),
            )
            return {
                "status": "error",
                "error": res.error or "ExecutionPipeline rejected order",
                "symbol": symbol,
                "side": side,
            }

        print(
            f"[NIJA-PRINT] ORDER ACCEPTED by ExecutionPipeline | "
            f"symbol={symbol} side={side} "
            f"filled_price={float(res.fill_price or 0.0):.6f} "
            f"filled_size_usd={float(res.filled_size_usd or 0.0):.2f} "
            f"broker={getattr(res, 'broker', preferred_broker)}",
            flush=True,
        )
        logger.critical(
            "✅ [BrokerAdapter] ORDER ACCEPTED by ExecutionPipeline | "
            "symbol=%s side=%s filled_price=%.6f filled_size_usd=%.2f broker=%s",
            symbol, side,
            float(res.fill_price or 0.0),
            float(res.filled_size_usd or 0.0),
            getattr(res, "broker", preferred_broker),
        )
        return {
            "status": "filled",
            "order_id": "pipeline",
            "symbol": symbol,
            "side": side,
            "filled_price": res.fill_price,
            "filled_size_usd": res.filled_size_usd,
            "broker": res.broker,
        }

    def _submit_limit_order_via_ecel(
        self,
        broker_client,
        symbol: str,
        side: str,
        size_usd: float,
        limit_price: float,
        available_balance_usd: Optional[float] = None,
        spendable_balance_usd: Optional[float] = None,
        strategy_name: str = "ExecutionEngine",
    ) -> Dict[str, Any]:
        """Place a limit order through the ECEL choke point.

        ECEL compiles the order, normalises qty/price to exchange grids,
        applies balance-aware sizing, and performs pre-flight assertions.
        Only a ``CompiledOrder`` with ``valid=True`` reaches the broker.
        """
        # Resolve broker label for ECEL
        broker_label = "coinbase"
        try:
            btype = getattr(broker_client, "broker_type", None)
            if btype is not None:
                raw = btype.value if hasattr(btype, "value") else str(btype)
                broker_label = raw.strip().lower()
        except Exception:
            pass

        # Fetch available balance for fee-aware sizing
        available_balance: Optional[float] = available_balance_usd
        spendable_balance: Optional[float] = spendable_balance_usd
        if available_balance is None and spendable_balance is None:
            cached_available, cached_total, _ = self._get_cached_balance_snapshot()
            available_balance = cached_available if cached_available is not None else cached_total
            if available_balance is not None:
                spendable_balance = max(
                    0.0,
                    available_balance * (1.0 - max(0.0, min(BALANCE_BUFFER_PCT, 0.50))),
                )

        if _ECEL_AVAILABLE and _get_ecel and _ECELCompileRequest:
            ecel = _get_ecel()
            req = _ECELCompileRequest(
                broker=broker_label,
                symbol=symbol,
                side=side,
                order_type="LIMIT",
                desired_notional_usd=size_usd,
                available_balance_usd=spendable_balance if spendable_balance is not None else available_balance,
                price_hint_usd=limit_price,
            )
            result = ecel.compile(req)

            if not result.accepted or result.compiled_order is None or not result.compiled_order.valid:
                logger.error(
                    "❌ ECEL REJECT (limit)\n"
                    "   • symbol: %s\n"
                    "   • reason: %s\n"
                    "   • attempted_notional: $%.4f\n"
                    "   • balance: %s",
                    symbol,
                    result.reason,
                    size_usd,
                    f"${available_balance:.4f}" if available_balance is not None else "unknown",
                )
                return {"status": "error", "error": result.reason, "symbol": symbol, "side": side}

            compiled = result.compiled_order
            compiled_qty = float(compiled.qty)
            compiled_price = float(compiled.price)

            logger.info(
                "🧾 ECEL ORDER (limit)\n"
                "   • symbol: %s\n"
                "   • side: %s\n"
                "   • price (normalised): %s\n"
                "   • qty (normalised): %s\n"
                "   • notional: $%.4f\n"
                "   • balance: %s\n"
                "   • fee_adj_cost: $%.4f",
                symbol, side,
                compiled.price, compiled.qty,
                float(compiled.qty * compiled.price),
                f"${spendable_balance:.4f}" if spendable_balance is not None else (
                    f"${available_balance:.4f}" if available_balance is not None else "unknown"
                ),
                float(compiled.qty * compiled.price) * 1.006,
            )
        else:
            # ECEL unavailable — fall back to uncompiled values and log clearly
            logger.warning(
                "⚠️ ECEL unavailable for limit order %s — using raw sizing (size_usd=%.4f, price=%.4f)",
                symbol, size_usd, limit_price,
            )
            compiled_qty = size_usd / limit_price if limit_price > 0 else 0.0
            compiled_price = limit_price

        try:
            order_result = broker_client.place_limit_order(
                symbol=symbol,
                side=side,
                size=compiled_qty,
                price=compiled_price,
            )
            return order_result if isinstance(order_result, dict) else {"status": "filled", "raw": order_result}
        except Exception as exc:
            logger.warning("⚠️ Limit order exception for %s via ECEL: %s", symbol, exc)
            return {"status": "error", "error": str(exc), "symbol": symbol, "side": side}

    def _assert_bootstrap_ready_for_execution_locks(self, strict: bool = False) -> bool:
        """
        Enforce state gate for execution locks.

        When strict=False: returns True/False immediately (non-blocking).
        When strict=True:  blocks until FSM reaches READY or RUNNING, then returns True.
                           Raises RuntimeError if the FSM does not reach a ready state
                           within the hard deadline (default 120 s).

        Args:
            strict: If True, block the caller until bootstrap is complete.

        Returns:
            bool: True if safe to acquire execution locks.

        Raises:
            RuntimeError: (strict=True only) FSM did not reach READY/RUNNING in time.
        """
        import time as _time

        _READY_STATES = {"READY", "RUNNING"}
        _POLL_INTERVAL = 0.25   # seconds between FSM state polls
        _STRICT_TIMEOUT = 120.0  # hard deadline when strict=True

        def _get_fsm():
            try:
                from bot.capital_flow_state_machine import get_capital_bootstrap_fsm as _fn
            except ImportError:
                from capital_flow_state_machine import get_capital_bootstrap_fsm as _fn  # type: ignore[import]
            return _fn()

        if not strict:
            # Non-blocking path — caller decides what to do with False.
            try:
                _cbfsm = _get_fsm()
                _state_val = _cbfsm.state.value
                if _state_val not in _READY_STATES:
                    logger.debug(
                        "EXECUTION_LOCK_STATE_GATE_BLOCKED capital_bootstrap_state=%s"
                        " — execution locks blocked until READY/RUNNING",
                        _state_val,
                    )
                    return False
                return True
            except Exception as _err:
                logger.warning(
                    "Execution lock state gate check failed: %s — blocking lock acquisition",
                    _err,
                )
                return False

        # strict=True — blocking synchronization barrier.
        _deadline = _time.monotonic() + _STRICT_TIMEOUT
        _warned = False
        _cbfsm = None
        while True:
            try:
                _cbfsm = _get_fsm()
                _state_val = _cbfsm.state.value
                if _state_val in _READY_STATES:
                    return True
                if not _warned:
                    logger.info(
                        "EXECUTION_LOCK_BARRIER_WAITING capital_bootstrap_state=%s"
                        " — holding lock acquisition until FSM reaches READY/RUNNING",
                        _state_val,
                    )
                    _warned = True
            except Exception as _err:
                logger.warning("Execution lock barrier FSM poll failed: %s", _err)

            if _time.monotonic() >= _deadline:
                raise RuntimeError(
                    f"ExecutionEngine lock barrier timeout: CapitalBootstrapFSM did not reach"
                    f" READY/RUNNING within {_STRICT_TIMEOUT}s — refusing lock acquisition"
                    f" (last known state={getattr(_cbfsm, 'state', 'unknown')})"
                )
            _time.sleep(_POLL_INTERVAL)

    def _get_closing_lock(self):
        """
        Return the real closing-lock context manager.

        Enforces a hard synchronization barrier: blocks until CapitalBootstrapFSM
        reaches READY or RUNNING before the lock is handed to the caller.
        Raises RuntimeError if the FSM does not become ready within the deadline.
        """
        self._assert_bootstrap_ready_for_execution_locks(strict=True)
        return self._closing_lock

    def _get_exit_lock(self):
        """
        Return the real exit-lock context manager.

        Enforces a hard synchronization barrier: blocks until CapitalBootstrapFSM
        reaches READY or RUNNING before the lock is handed to the caller.
        Raises RuntimeError if the FSM does not become ready within the deadline.
        """
        self._assert_bootstrap_ready_for_execution_locks(strict=True)
        return self._exit_lock

    def _get_market_microstructure(self, symbol: str) -> Any:
        """
        Get current market microstructure data for execution optimization.

        Args:
            symbol: Trading pair symbol

        Returns:
            MarketMicrostructure object or None if unavailable
        """
        if not EXECUTION_INTELLIGENCE_AVAILABLE or not self.broker_client or MarketMicrostructure is None:
            return None

        try:
            import time

            # Try to get quote data from broker
            if hasattr(self.broker_client, 'get_quote'):
                quote = self.broker_client.get_quote(symbol)
                if not quote:
                    return None

                bid = quote.get('bid', 0.0)
                ask = quote.get('ask', 0.0)

                if bid <= 0 or ask <= 0:
                    return None

                # Calculate spread
                spread_pct = (ask - bid) / bid if bid > 0 else 0.001
                mid_price = (bid + ask) / 2.0

                # Get volume if available
                volume_24h = quote.get('volume_24h', 0.0) or 1000000.0  # Default to 1M

                # Get order book depth if available
                bid_depth = quote.get('bid_depth', 0.0) or volume_24h * 0.01
                ask_depth = quote.get('ask_depth', 0.0) or volume_24h * 0.01

                # Estimate volatility from spread (rough approximation)
                volatility = spread_pct * 2.0

                return MarketMicrostructure(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    spread_pct=spread_pct,
                    volume_24h=volume_24h,
                    bid_depth=bid_depth,
                    ask_depth=ask_depth,
                    volatility=volatility,
                    price=mid_price,
                    timestamp=time.time()
                )

            # Fallback: try to get market data
            if hasattr(self.broker_client, 'get_market_data'):
                market_data = self.broker_client.get_market_data(symbol)
                if market_data and 'price' in market_data:
                    price = market_data['price']
                    # Estimate bid/ask with typical spread
                    estimated_spread = price * 0.001  # 0.1% spread
                    bid = price - estimated_spread / 2.0
                    ask = price + estimated_spread / 2.0

                    return MarketMicrostructure(
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        spread_pct=0.001,
                        volume_24h=market_data.get('volume_24h', 1000000.0),
                        bid_depth=10000.0,
                        ask_depth=10000.0,
                        volatility=market_data.get('volatility', 0.01),
                        price=price,
                        timestamp=time.time()
                    )

            return None

        except Exception as e:
            logger.debug(f"Could not get market microstructure for {symbol}: {e}")
            return None

    def _optimize_execution_with_intelligence(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        urgency: float = 0.7
    ) -> Any:
        """
        Use Execution Intelligence to optimize order execution.

        Args:
            symbol: Trading pair symbol
            side: 'buy' or 'sell' (or 'long'/'short')
            size_usd: Order size in USD
            urgency: Execution urgency (0=patient, 1=immediate)

        Returns:
            ExecutionPlan or None if optimization unavailable
        """
        if not self.execution_intelligence:
            return None

        # Get market microstructure
        market_data = self._get_market_microstructure(symbol)
        if not market_data:
            logger.debug(f"Market microstructure unavailable for {symbol}, skipping optimization")
            return None

        # Normalize side to buy/sell
        normalized_side = 'buy' if side in ['long', 'buy'] else 'sell'

        try:
            # Get optimized execution plan
            plan = self.execution_intelligence.optimize_execution(
                symbol=symbol,
                side=normalized_side,
                size_usd=size_usd,
                market_data=market_data,
                urgency=urgency,
                allow_splitting=False  # For now, disable splitting to keep things simple
            )

            logger.info(f"🎯 Execution Intelligence Plan for {symbol}:")
            logger.info(f"   Order Type: {plan.order_type.value}")
            logger.info(f"   Expected Slippage: {plan.expected_slippage*100:.3f}%")
            logger.info(f"   Expected Spread Cost: {plan.expected_spread_cost*100:.3f}%")
            logger.info(f"   Total Execution Cost: {plan.total_cost_pct*100:.3f}%")
            logger.info(f"   Market Impact: {plan.market_impact_pct*100:.3f}%")

            if plan.warnings:
                for warning in plan.warnings:
                    logger.warning(f"   ⚠️ {warning}")

            return plan

        except Exception as e:
            logger.warning(f"Execution optimization failed for {symbol}: {e}")
            return None

    def _record_execution_result(
        self,
        symbol: str,
        expected_price: float,
        actual_price: float,
        side: str
    ):
        """
        Record execution result for learning.

        Args:
            symbol: Trading pair symbol
            expected_price: Expected execution price
            actual_price: Actual fill price
            side: 'buy' or 'sell'
        """
        if not self.execution_intelligence:
            return

        try:
            # Get current spread for recording
            market_data = self._get_market_microstructure(symbol)
            spread_pct = market_data.spread_pct if market_data else 0.001

            self.execution_intelligence.record_execution_result(
                symbol=symbol,
                expected_price=expected_price,
                actual_price=actual_price,
                side=side,
                spread_pct=spread_pct
            )

        except Exception as e:
            logger.debug(f"Could not record execution result: {e}")

    def _handle_geographic_restriction_error(self, symbol: str, error_msg: str):
        """
        Handle geographic restriction errors by adding symbol to blacklist

        Thread-safe helper method for processing geographic restriction errors.

        Args:
            symbol: Trading symbol that was rejected
            error_msg: Error message from broker
        """
        if RESTRICTION_MANAGER_AVAILABLE and is_geographic_restriction_error(str(error_msg)):
            logger.warning("=" * 70)
            logger.warning("🚫 GEOGRAPHIC RESTRICTION DETECTED")
            logger.warning("=" * 70)
            logger.warning(f"   Symbol: {symbol}")
            logger.warning(f"   Error: {error_msg}")
            logger.warning("   Adding to permanent blacklist to prevent future attempts")
            logger.warning("=" * 70)
            add_restricted_symbol(symbol, str(error_msg))

    def _get_broker_round_trip_fee(self) -> float:
        """
        Get broker-specific round-trip fee for fee-aware profit calculations.

        CRITICAL FIX (Jan 25, 2026): Make profit-taking broker-aware
        - Kraken: 0.36% round-trip (0.16% taker x2 + 0.04% spread)
        - Coinbase: 1.4% round-trip (0.6% taker x2 + 0.2% spread)
        - Binance: 0.28% round-trip (0.1% taker x2 + 0.08% spread)
        - OKX: 0.30% round-trip (0.1% taker x2 + 0.1% spread)

        Returns:
            Round-trip fee as decimal (e.g., 0.0036 for Kraken = 0.36%)
        """
        if not self.broker_client or not hasattr(self.broker_client, 'broker_type'):
            # No broker client available - use Coinbase default (conservative)
            return DEFAULT_ROUND_TRIP_FEE  # 1.4%

        broker_type = self.broker_client.broker_type
        broker_name = None

        # Extract broker name from broker_type (handle both Enum and string)
        if hasattr(broker_type, 'value'):
            broker_name = broker_type.value.lower()
        elif isinstance(broker_type, str):
            broker_name = broker_type.lower()
        else:
            broker_name = str(broker_type).lower()

        # Return broker-specific fees
        # PROFITABILITY FIX: Use actual broker fees instead of Coinbase default
        broker_fees = {
            'kraken': 0.0036,      # 0.36% - 4x cheaper than Coinbase
            'coinbase': 0.014,     # 1.4% - baseline
            'binance': 0.0028,     # 0.28% - cheapest
            'okx': 0.0030,         # 0.30% - very cheap
            'alpaca': 0.0000,      # 0% - stock trading (no crypto fees)
        }

        fee = broker_fees.get(broker_name, DEFAULT_ROUND_TRIP_FEE)

        # Log on first call for debugging
        if not hasattr(self, '_logged_broker_fee'):
            self._logged_broker_fee = True
            logger.info(f"🎯 Using {broker_name} round-trip fee: {fee*100:.2f}% for profit calculations")

        return fee

    def _get_broker_label(self) -> str:
        """Return a stable broker label for execution diagnostics."""
        return resolve_broker_label(self.broker_client)

    def _get_balance_cache_key(self) -> str:
        """Return a balance-cache key that is unique per broker account."""
        return format_broker_identity(self.broker_client)

    @staticmethod
    def _extract_balance_values(balance_data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """Return (available_balance, total_balance) from a balance dict.

        Key precedence (first non-zero value wins):
        available_balance → trading_balance → total_balance → total_funds.
        If only trading_balance exists, it becomes available_balance; if only
        total_balance/total_funds exists, those become the total. Missing or
        empty balance_data yields (None, None).
        """
        if not balance_data:
            return None, None
        available = None
        total = None
        try:
            available = float(
                balance_data.get(
                    "available_balance",
                    balance_data.get(
                        "trading_balance",
                        balance_data.get(
                            "total_balance",
                            balance_data.get("total_funds", 0.0),
                        ),
                    ),
                )
            )
        except Exception:
            available = None
        try:
            total = float(
                balance_data.get(
                    "total_balance",
                    balance_data.get(
                        "total_funds",
                        balance_data.get("trading_balance", available or 0.0),
                    ),
                )
            )
        except Exception:
            total = None
        return available, total

    def _get_cached_balance_snapshot(self) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
        """Return cached (available_balance, total_balance, raw_balance_dict) without polling.

        Prefer this helper during sizing to avoid unnecessary API calls.

        Fallback order:
        BalanceService detailed → BalanceService scalar → broker_client._balance_cache →
        broker_client._last_known_balance → (None, None, {}).
        """
        broker_key = self._get_balance_cache_key()
        broker_label = self._get_broker_label()

        if BALANCE_SERVICE_AVAILABLE and BalanceService is not None:
            detailed = BalanceService.get_detailed(broker_key)
            if detailed:
                available, total = self._extract_balance_values(detailed)
                if available is not None or total is not None:
                    return available, total, detailed

        # Fallback to broker-local caches (no network call)
        if self.broker_client is not None:
            cached_detail = getattr(self.broker_client, "_balance_cache", None)
            if isinstance(cached_detail, dict):
                available, total = self._extract_balance_values(cached_detail)
                if available is not None or total is not None:
                    return available, total, cached_detail
            if hasattr(self.broker_client, "get_account_balance_detailed"):
                try:
                    detailed = self.broker_client.get_account_balance_detailed(verbose=False)
                    if isinstance(detailed, dict) and not detailed.get("error", False):
                        available, total = self._extract_balance_values(detailed)
                        if available is not None or total is not None:
                            return available, total, detailed
                except Exception:
                    pass
            cached_scalar = getattr(self.broker_client, "_last_known_balance", None)
            if isinstance(cached_scalar, (int, float)) and cached_scalar > 0:
                scalar = float(cached_scalar)
                cached = {
                    "total_balance": scalar,
                    "total_funds": scalar,
                }
                return None, scalar, cached

        if BALANCE_SERVICE_AVAILABLE and BalanceService is not None:
            scalar = BalanceService.get(broker_key)
            if scalar <= 0 and broker_key != broker_label:
                scalar = BalanceService.get(broker_label)
            if scalar > 0:
                cached = {
                    "total_balance": scalar,
                    "total_funds": scalar,
                }
                return None, scalar, cached

        return None, None, {}

    @staticmethod
    def _apply_exchange_floor(min_value: Optional[float]) -> float:
        """Clamp the requested minimum to the exchange hard floor."""
        try:
            if min_value is not None:
                return max(EXCHANGE_HARD_FLOOR_USD, float(min_value))
        except Exception as exc:
            logger.debug("Exchange floor conversion failed: %s", exc)
        return EXCHANGE_HARD_FLOOR_USD

    def _extract_order_failure_details(
        self,
        broker_response: Optional[Dict] = None,
        exc: Optional[Exception] = None,
    ) -> Dict[str, str]:
        """Extract a compact, human-readable failure payload for logs.

        When the Kraken error taxonomy layer is available the hint, retry
        policy, and canonical error code are taken directly from it so the
        execution engine never has to guess the correct response.
        """
        status = str((broker_response or {}).get("status") or ("exception" if exc else "unknown")).lower()
        error = ""
        message = ""

        if broker_response:
            raw_error = broker_response.get("error", "")
            raw_message = broker_response.get("message", "")
            if isinstance(raw_error, (list, tuple)):
                error = ", ".join(str(item) for item in raw_error if item)
            else:
                error = str(raw_error or "")
            message = str(raw_message or "")

        if exc is not None and not error:
            error = str(exc)

        combined = " | ".join(part for part in (error, message) if part).strip() or "Unknown execution failure"
        normalized = combined.lower()

        # ── Taxonomy-driven classification ───────────────────────────────
        retry_policy_value: Optional[str] = None
        canonical_code: Optional[str] = None
        if _KRAKEN_TAXONOMY_AVAILABLE and _classify_kraken_error is not None and error:
            _taxonomy = _classify_kraken_error(error)
            hint = _taxonomy.remediation
            retry_policy_value = _taxonomy.policy.value
            canonical_code = _taxonomy.canonical_code
        else:
            # Fallback: manual keyword hints for non-Kraken or degraded paths
            hint = "Inspect broker rejection payload"
            if "too small" in normalized or "minimum" in normalized or "min notional" in normalized:
                hint = "Check minimum order size / exchange notional floor"
            elif "insufficient" in normalized or "fund" in normalized or "balance" in normalized:
                hint = "Check per-broker available balance and fee-adjusted sizing"
            elif "unsupported" in normalized or "invalid product" in normalized or "symbol" in normalized:
                hint = "Check symbol support / exchange restrictions"
            elif "nonce" in normalized or "signature" in normalized or "eapi:invalid nonce" in normalized:
                hint = "Check Kraken nonce synchronization / API signature path"
            elif "geographic" in normalized or "region" in normalized or "jurisdiction" in normalized:
                hint = "Check exchange geographic restrictions for this symbol"

        error_code = canonical_code or error or message or status or "UNKNOWN_REJECTION"
        error_code = error_code[:120].upper().replace(" ", "_")

        result: Dict[str, str] = {
            "status": status,
            "error_code": error_code,
            "detail": combined,
            "hint": hint,
        }
        if retry_policy_value is not None:
            result["retry_policy"] = retry_policy_value
        return result

    def _normalized_order_status(self, broker_response: Optional[Dict]) -> str:
        """Return normalized lowercase broker status for branch checks."""
        if not broker_response:
            return ""
        return str(broker_response.get("status", "")).lower().strip()

    def _log_order_failure(
        self,
        symbol: str,
        position_size: float,
        broker_response: Optional[Dict] = None,
        exc: Optional[Exception] = None,
    ) -> None:
        """Emit a structured execution-failure log with broker-level detail."""
        details = self._extract_order_failure_details(broker_response=broker_response, exc=exc)
        logger.error(
            "❌ Order rejected | broker=%s | symbol=%s | size=$%.2f | status=%s | reason=%s",
            self._get_broker_label(),
            symbol,
            position_size,
            details["status"],
            details["detail"],
        )
        logger.error("   Hint: %s", details["hint"])
        logger.error("   ⚠️  DO NOT RECORD TRADE - Order did not execute")

    def _confirm_order_fill(
        self,
        symbol: str,
        side: str,
        expected_quantity: float,
        broker_response: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Attempt to confirm fills via ExecutionConfirmationLayer when available.

        expected_quantity is the base-asset quantity implied by the order.
        Mutates broker_response in-place by adding ``filled_price``,
        ``filled_volume``, and updating ``status`` when confirmation succeeds.
        If confirmation is unavailable or fails, the original response is
        returned unchanged.
        """
        if not broker_response or not isinstance(broker_response, dict):
            return broker_response
        if not EXECUTION_CONFIRMATION_AVAILABLE or get_execution_confirmation_layer is None:
            return broker_response
        if self.broker_client is None:
            return broker_response
        if expected_quantity <= 0:
            logger.debug("Skipping fill confirmation for %s: expected_quantity <= 0", symbol)
            return broker_response

        order_id = broker_response.get("order_id") or broker_response.get("id")
        if not order_id:
            return broker_response
        if str(order_id).lower() in SYNTHETIC_ORDER_IDS:
            return broker_response

        status = self._normalized_order_status(broker_response)
        if status in ("filled", "closed"):
            return broker_response

        try:
            ecl = get_execution_confirmation_layer()
            confirm = ecl.confirm_existing_order(
                broker=self.broker_client,
                symbol=symbol,
                side=side,
                expected_size=max(0.0, expected_quantity),
                order_id=str(order_id),
                initial_response=broker_response,
            )
        except Exception as exc:
            logger.debug("Fill confirmation skipped for %s (%s)", symbol, exc)
            return broker_response

        if confirm is None:
            return broker_response

        if confirm.avg_price and not broker_response.get("filled_price"):
            broker_response["filled_price"] = confirm.avg_price
        if confirm.filled_size > 0:
            broker_response["filled_volume"] = confirm.filled_size

        if FillStatus is not None:
            if confirm.status == FillStatus.FILLED:
                broker_response["status"] = "filled"
                logger.info("✅ Fill confirmed: %s %s @ %s", symbol, side, confirm.avg_price or "market")
            elif confirm.status == FillStatus.PARTIAL:
                broker_response["status"] = "pending"
                logger.warning(
                    "⚠️ Partial fill confirmed: %s %s (%.2f%%)",
                    symbol,
                    side,
                    confirm.filled_pct,
                )

        return broker_response

    def _resolve_expected_win_rate(self, take_profit_levels: Dict[str, float]) -> float:
        """Resolve expected win probability for expectancy gate."""
        # 1) Explicit per-trade values (preferred)
        for key in ("expected_win_rate", "win_probability", "prob_win"):
            if key in take_profit_levels:
                try:
                    p = float(take_profit_levels[key])
                    if p > 1.0:
                        p = p / 100.0
                    return max(0.01, min(0.99, p))
                except (TypeError, ValueError):
                    pass

        # 2) Environment default (percentage)
        try:
            p_env = float(os.getenv("EXPECTED_WIN_RATE_PCT", str(DEFAULT_EXPECTED_WIN_RATE * 100.0))) / 100.0
            return max(0.01, min(0.99, p_env))
        except (TypeError, ValueError):
            return DEFAULT_EXPECTED_WIN_RATE

    def _normalize_regime(self, take_profit_levels: Dict[str, float]) -> str:
        """Best-effort regime extraction from trade context payload."""
        regime = (
            take_profit_levels.get("regime")
            or take_profit_levels.get("market_regime")
            or take_profit_levels.get("regime_family")
            or ""
        )
        return str(regime).strip().lower()

    def _compute_edge_score(self, p_win: float, reward_risk: float, cost_penalty: float) -> float:
        """Expected profitability score used as hard pre-trade gate."""
        p_loss = 1.0 - p_win
        return (p_win * reward_risk) - (p_loss * 1.0) - cost_penalty

    def _compute_kelly_fraction(self, p_win: float, reward_risk: float) -> float:
        """Kelly-lite position fraction (clamped)."""
        if reward_risk <= 0:
            return 0.0
        q = 1.0 - p_win
        kelly = ((reward_risk * p_win) - q) / reward_risk
        if kelly <= 0:
            return 0.0
        return min(kelly, MAX_KELLY_FRACTION)

    def _build_expectancy_bucket_key(self, symbol: str, regime: str = "") -> str:
        """Build stable key for expectancy tracking buckets."""
        regime_norm = (regime or "unspecified").strip().lower()
        return f"{symbol}|{regime_norm}"

    def get_expectancy_kill_switch_status(self, max_rows: int = 25) -> Dict[str, Any]:
        """Return a snapshot of expectancy kill-switch state for diagnostics/UI."""
        now = datetime.now()
        auto_active: List[Dict[str, Any]] = []
        manual_or_legacy: List[str] = []
        expired_reenabled: List[str] = []

        for bucket_key in sorted(self._disabled_pairs):
            until_ts = self._disabled_until.get(bucket_key)
            if until_ts is None:
                manual_or_legacy.append(bucket_key)
                continue

            if until_ts <= now:
                expired_reenabled.append(bucket_key)
                continue

            remaining_seconds = max(0, int((until_ts - now).total_seconds()))
            auto_active.append(
                {
                    "bucket": bucket_key,
                    "disabled_until": until_ts.isoformat(),
                    "remaining_seconds": remaining_seconds,
                    "remaining_minutes": round(remaining_seconds / 60.0, 2),
                }
            )

        # Opportunistically clean up expired cooldown buckets.
        for bucket_key in expired_reenabled:
            self._disabled_pairs.discard(bucket_key)
            self._disabled_until.pop(bucket_key, None)

        auto_active.sort(key=lambda x: x["remaining_seconds"], reverse=True)
        if max_rows > 0:
            auto_active = auto_active[:max_rows]

        return {
            "disabled_total": len(self._disabled_pairs),
            "auto_cooldown_active": len(auto_active),
            "manual_or_legacy_active": len(manual_or_legacy),
            "force_enable_buckets": sorted(self._force_enable_buckets),
            "active_buckets": auto_active,
            "manual_or_legacy_buckets": manual_or_legacy[:max_rows] if max_rows > 0 else manual_or_legacy,
            "just_reenabled": expired_reenabled,
        }

    def log_expectancy_kill_switch_status(self, max_rows: int = 10) -> None:
        """Emit a concise log summary of current expectancy kill-switch buckets."""
        status = self.get_expectancy_kill_switch_status(max_rows=max_rows)
        force_enable_buckets = status.get("force_enable_buckets", [])
        active_buckets = status.get("active_buckets", [])
        if not isinstance(force_enable_buckets, list):
            force_enable_buckets = []
        if not isinstance(active_buckets, list):
            active_buckets = []

        logger.info(
            "🧭 EXPECTANCY KILL-SWITCH STATUS: total=%d auto=%d manual=%d force_enable=%d",
            int(status.get("disabled_total", 0)),
            int(status.get("auto_cooldown_active", 0)),
            int(status.get("manual_or_legacy_active", 0)),
            len(force_enable_buckets),
        )

        for item in active_buckets:
            if not isinstance(item, dict):
                continue
            logger.info(
                "   ⛔ %s | remaining=%.2f min | until=%s",
                item.get("bucket", "unknown"),
                float(item.get("remaining_minutes", 0.0)),
                item.get("disabled_until", "unknown"),
            )

    def _is_expectancy_bucket_blocked(self, symbol: str, bucket_key: str) -> bool:
        """Return True if a symbol/regime bucket is currently blocked."""
        if symbol not in self._disabled_pairs and bucket_key not in self._disabled_pairs:
            return False

        # Manual force-enable for emergency recovery without code edits.
        if symbol in self._force_enable_buckets or bucket_key in self._force_enable_buckets:
            self._disabled_pairs.discard(symbol)
            self._disabled_pairs.discard(bucket_key)
            self._disabled_until.pop(symbol, None)
            self._disabled_until.pop(bucket_key, None)
            logger.warning("🟢 EXPECTANCY OVERRIDE: force-enabled %s (bucket=%s)", symbol, bucket_key)
            return False

        # Legacy symbol-level disables remain blocked unless explicitly re-enabled.
        if bucket_key not in self._disabled_pairs:
            return True

        until_ts = self._disabled_until.get(bucket_key)
        if until_ts is None:
            return True

        if datetime.now() < until_ts:
            return True

        # Cooldown expired: allow bucket to trade again.
        self._disabled_pairs.discard(bucket_key)
        self._disabled_until.pop(bucket_key, None)
        logger.warning(
            "🟢 EXPECTANCY COOLDOWN EXPIRED: re-enabled bucket %s after %d minutes",
            bucket_key,
            EXPECTANCY_DISABLE_COOLDOWN_MINUTES,
        )
        return False

    def _record_pair_expectancy(self, symbol: str, expectancy_pct: float, regime: str = "") -> None:
        """Record realized expectancy sample and auto-disable weak symbol+regime buckets."""
        bucket_key = self._build_expectancy_bucket_key(symbol, regime)
        samples = self._pair_realized_expectancy[bucket_key]
        samples.append(float(expectancy_pct))

        if len(samples) < PAIR_EXPECTANCY_MIN_TRADES:
            return

        avg_exp = sum(samples) / len(samples)
        if avg_exp < 0 and bucket_key not in self._disabled_pairs:
            self._disabled_pairs.add(bucket_key)
            self._disabled_until[bucket_key] = datetime.now() + timedelta(minutes=EXPECTANCY_DISABLE_COOLDOWN_MINUTES)
            logger.critical(
                "🛑 BUCKET AUTO-DISABLED: %s | rolling_expectancy=%.4f%% | trades=%d | cooldown=%dmin",
                bucket_key,
                avg_exp * 100.0,
                len(samples),
                EXPECTANCY_DISABLE_COOLDOWN_MINUTES,
            )

    # ── Execution Result Contract ──────────────────────────────────────────────

    def _emit_execution_result(
        self,
        symbol: str,
        side: str,
        broker_response: Optional[Dict],
        t0: float,
        exc: Optional[Exception] = None,
    ) -> None:
        """
        Build and log the canonical EXECUTION_RESULT line for a single order.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        side:
            ``"buy"`` or ``"sell"``.
        broker_response:
            Raw dict returned by the broker client, or ``None`` on exception.
        t0:
            ``time.monotonic()`` timestamp captured just before calling the
            broker so that latency can be calculated.
        exc:
            Exception raised by the broker call if any (``None`` on success).
        """
        _exec_result_cls = _ExecResult
        _order_status_enum = _OrderStatus
        _log_exec_fn = _log_exec_result
        if (
            not _EXEC_RESULT_AVAILABLE
            or not callable(_exec_result_cls)
            or _order_status_enum is None
            or not callable(_log_exec_fn)
        ):
            return

        _status_failed = getattr(_order_status_enum, "FAILED", None)
        _status_rejected = getattr(_order_status_enum, "REJECTED", None)
        _status_accepted = getattr(_order_status_enum, "ACCEPTED", None)
        if _status_failed is None or _status_rejected is None or _status_accepted is None:
            return

        latency_ms = int((_time.monotonic() - t0) * 1000)

        if exc is not None:
            # Broker call raised — classify via taxonomy then emit FAILED
            _exc_str = str(exc)[:120]
            _retry_policy = None
            if _KRAKEN_TAXONOMY_AVAILABLE and _classify_kraken_error is not None:
                _t = _classify_kraken_error(_exc_str)
                _retry_policy = _t.policy
            result = _exec_result_cls(
                status=_status_failed,
                symbol=symbol,
                side=side,
                exchange_order_id=None,
                error_code=_exc_str,
                latency_ms=latency_ms,
                retry_policy=_retry_policy,
            )
        elif broker_response is None or str(broker_response.get("status", "")).lower() in {
            "error", "unfilled", "skipped", "rejected"
        }:
            details = self._extract_order_failure_details(broker_response=broker_response, exc=None)
            _retry_policy_val = details.get("retry_policy")
            _retry_policy_obj = None
            if _retry_policy_val and _KRAKEN_TAXONOMY_AVAILABLE and _KrakenRetryPolicy is not None:
                try:
                    _retry_policy_obj = _KrakenRetryPolicy(_retry_policy_val)
                except (ValueError, KeyError):
                    pass
            result = _exec_result_cls(
                status=_status_rejected,
                symbol=symbol,
                side=side,
                exchange_order_id=None,
                error_code=details["error_code"],
                latency_ms=latency_ms,
                retry_policy=_retry_policy_obj,
            )
        else:
            order_id = (
                broker_response.get("order_id")
                or broker_response.get("id")
                or broker_response.get("client_order_id")
            )
            result = _exec_result_cls(
                status=_status_accepted,
                symbol=symbol,
                side=side,
                exchange_order_id=str(order_id) if order_id else None,
                error_code=None,
                latency_ms=latency_ms,
            )

        _log_exec_fn(result)

    def can_execute_trade(self, order_size_usd: float) -> bool:
        """
        Hard gate: return True only when the system has confirmed capital
        sufficient to cover *order_size_usd*.

        This is the execution layer's capital guard (FIX 4).  It is called
        automatically by :meth:`execute_entry` before any broker interaction.
        External callers (e.g. the strategy loop) may also call it directly
        as a pre-flight check.

        Logic
        -----
        1. Fetch the total available balance via :class:`ActiveCapital`.
        2. Block (return ``False``) if balance ≤ 0.
        3. Block (return ``False``) if the requested order size exceeds the
           available balance.
        4. Allow (return ``True``) otherwise.

        If :class:`ActiveCapital` is unavailable or raises
        :class:`CapitalIntegrityError`, the method logs a warning and returns
        ``False`` (fail-closed).

        Parameters
        ----------
        order_size_usd:
            Requested order notional value in USD.

        Returns
        -------
        bool
        """
        if not ACTIVE_CAPITAL_AVAILABLE or get_active_capital is None:
            logger.warning("⚠️ ActiveCapital not available — capital gate skipped (fail-open)")
            return True  # fail-open when capital layer is absent (legacy compatibility)

        # ── FORCE_TRADE bypass: when operator override flags are active and
        # ActiveCapital raises CapitalIntegrityError (authority not yet hydrated),
        # fail-open so the order can proceed.  The broker adapter enforces the
        # real account balance before any exchange interaction, so this bypass
        # only skips the capital-pipeline gate — not the actual balance check.
        # This is the second half of the "7000+ cycles, zero trades" fix:
        # active_capital.py now returns a fallback value under FORCE_TRADE, but
        # this catch ensures any residual CapitalIntegrityError is also bypassed.
        _force_trade_bypass_cet = (
            os.getenv("FORCE_TRADE", "").strip().lower()
            in ("1", "true", "yes", "on", "enabled")
            or os.getenv("FORCE_TRADE_MODE", "").strip().lower()
            in ("1", "true", "yes", "on", "enabled")
            or os.getenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "").strip().lower()
            in ("1", "true", "yes", "on", "enabled")
            or os.getenv("NIJA_FORCE_ACTIVATION", "").strip().lower()
            in ("1", "true", "yes", "on", "enabled")
        )

        try:
            balance = get_active_capital().get_total_available_balance()
        except CapitalIntegrityError as exc:
            if _force_trade_bypass_cet:
                logger.warning(
                    "⚡ [can_execute_trade] FORCE_TRADE bypass: CapitalIntegrityError suppressed — "
                    "failing open so order can proceed. error=%s "
                    "(FORCE_TRADE / NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK active)",
                    exc,
                )
                return True
            logger.warning("🚫 CAPITAL INTEGRITY ERROR — trade blocked: %s", exc)
            return False
        except Exception as exc:
            if _force_trade_bypass_cet:
                logger.warning(
                    "⚡ [can_execute_trade] FORCE_TRADE bypass: capital check exception suppressed — "
                    "failing open so order can proceed. error=%s",
                    exc,
                )
                return True
            logger.warning("🚫 CAPITAL CHECK FAILED — trade blocked: %s", exc)
            return False

        if balance <= 0:
            if _force_trade_bypass_cet:
                logger.warning(
                    "⚡ [can_execute_trade] FORCE_TRADE bypass: balance=$%.2f ≤ 0 — "
                    "failing open so order can proceed. "
                    "Broker adapter will enforce real balance limits.",
                    balance,
                )
                return True
            logger.warning(
                "🚫 NO CAPITAL AVAILABLE — trade blocked "
                "(balance=$%.2f, order_size=$%.2f)",
                balance,
                order_size_usd,
            )
            return False

        if order_size_usd > balance:
            logger.warning(
                "🚫 ORDER EXCEEDS BALANCE — trade blocked "
                "(order_size=$%.2f > balance=$%.2f)",
                order_size_usd,
                balance,
            )
            return False

        return True

    def execute_entry(self, symbol: str, side: str, position_size: float,  # pyright: ignore[reportGeneralTypeIssues]
                     entry_price: float, stop_loss: float,
                     take_profit_levels: Dict[str, float]) -> Optional[Dict]:
        """
        Execute entry order

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            side: 'long' or 'short'
            position_size: Position size in USD
            entry_price: Expected entry price
            stop_loss: Stop loss price
            take_profit_levels: Dictionary with tp1, tp2, tp3

        Returns:
            Position dictionary or None if failed
        """
        try:
            def _trace(
                stage: str,
                outcome: str,
                reason: str,
                *,
                terminal: bool = False,
                extra: Optional[Dict[str, Any]] = None,
            ) -> None:
                if not SIGNAL_FUNNEL_AVAILABLE or get_signal_funnel is None:
                    return
                try:
                    get_signal_funnel().record_execution_stage(
                        pair=symbol,
                        side=side,
                        stage=stage,
                        outcome=outcome,
                        reason=reason,
                        terminal=terminal,
                        extra=extra or {},
                    )
                except Exception:
                    pass

            def _pfunnel(method: str) -> None:
                if not _PIPELINE_FUNNEL_AVAILABLE or _get_pipeline_funnel is None:
                    return
                try:
                    getattr(_get_pipeline_funnel(), f"record_{method}")(symbol)
                except Exception:
                    pass

            logger.info(
                "📋 [ExecutionEngine.execute_entry] ENTRY GATE STARTED | symbol=%s side=%s "
                "position_size=$%.2f entry_price=%.6f",
                symbol, side, position_size, entry_price,
            )

            # Bootstrap authority gate: execution is blocked until bootstrap
            # finalization grants runtime execution_authority.
            try:
                try:
                    from bot.bootstrap_state_machine import get_bootstrap_fsm as _get_bootstrap_fsm
                except ImportError:
                    from bootstrap_state_machine import get_bootstrap_fsm as _get_bootstrap_fsm  # type: ignore[import]
                _bfsm = _get_bootstrap_fsm()
                _has_auth = (
                    _bfsm.has_execution_authority()
                    if hasattr(_bfsm, "has_execution_authority")
                    else bool(getattr(_bfsm, "execution_authority", False))
                )
                logger.info(
                    "🔑 [ExecutionEngine] Bootstrap authority gate | symbol=%s has_auth=%s "
                    "fsm_state=%s",
                    symbol,
                    _has_auth,
                    getattr(_bfsm, "state", getattr(_bfsm, "_state", "unknown")),
                )
                if not _has_auth:
                    _force_trade_now_bootstrap = (
                        os.getenv("FORCE_TRADE", "false").lower() in ("true", "1", "yes")
                        or os.getenv("FORCE_TRADE_MODE", "false").lower() in ("true", "1", "yes")
                        or os.getenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "false").lower() in ("true", "1", "yes", "on", "enabled")
                    )
                    if _force_trade_now_bootstrap:
                        logger.warning(
                            "⚠️  EXECUTION AUTHORITY BLOCK bypassed for %s — bootstrap execution_authority=false "
                            "(BootstrapFSM state=%s) but FORCE_TRADE / FORCE_TRADE_MODE / NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK "
                            "is set to a truthy value overriding this gate.",
                            symbol,
                            getattr(_bfsm, "state", getattr(_bfsm, "_state", "unknown")),
                        )
                    else:
                        logger.error(
                            "🚫 EXECUTION AUTHORITY BLOCK: %s rejected — bootstrap execution_authority=false "
                            "(BootstrapFSM state=%s). Set FORCE_TRADE, FORCE_TRADE_MODE, or "
                            "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK to a truthy value to bypass, "
                            "or wait for bootstrap to complete.",
                            symbol,
                            getattr(_bfsm, "state", getattr(_bfsm, "_state", "unknown")),
                        )
                        _trace("ecel", "rejected", "bootstrap_execution_authority_false", terminal=True)
                        return None
            except Exception as _auth_exc:
                logger.warning("Bootstrap execution authority check skipped (non-fatal): %s", _auth_exc)

            _balance_available, _balance_total, _ = self._get_cached_balance_snapshot()

            # ─── FIX 1: MINIMUM BALANCE GATE ────────────────────────────────────────
            # Skip accounts that cannot meet the minimum trading balance.
            # In FORCE_TRADE_MODE (micro test mode), bypass this gate.
            if self.broker_client is not None and not FORCE_TRADE_MODE:
                _scalar_balance = _balance_total if _balance_total is not None else _balance_available
                if _scalar_balance is None:
                    logger.debug("Balance gate skipped: no cached balance snapshot for %s", symbol)
                elif _scalar_balance <= 0:
                    logger.warning(
                        "⛔ FIX1 BALANCE GATE: Skipping %s — zero or negative balance ($%.2f)",
                        symbol,
                        _scalar_balance,
                    )
                    _trace("ecel", "rejected", f"balance_gate_zero_or_negative:{_scalar_balance:.2f}", terminal=True)
                    return None

            # ─── FIX 2: MINIMUM ORDER SIZE GATE ─────────────────────────────────────
            broker_label = self._get_broker_label()
            _available_usd = _balance_available if _balance_available is not None else _balance_total
            _spendable_usd = None
            if _available_usd is not None:
                _spendable_usd = max(
                    0.0,
                    _available_usd * (1.0 - max(0.0, min(BALANCE_BUFFER_PCT, 0.50))),
                )
                if position_size > _spendable_usd > 0:
                    logger.info(
                        "🔒 Spendable-balance cap: requested $%.2f -> $%.2f (available=$%.2f, buffer=%.1f%%)",
                        position_size,
                        _spendable_usd,
                        _available_usd,
                        BALANCE_BUFFER_PCT * 100.0,
                    )
                    position_size = _spendable_usd

            _min_notional_floor = None
            if MIN_NOTIONAL_GATE_AVAILABLE and get_minimum_notional_gate:
                try:
                    _notional_gate = get_minimum_notional_gate()
                    _min_notional_floor = _notional_gate.config.get_min_notional_for_broker(
                        broker_label,
                        balance=_available_usd or 0.0,
                    )
                    if position_size < _min_notional_floor:
                        if _spendable_usd is not None and _min_notional_floor > _spendable_usd:
                            logger.warning(
                                "⛔ FIX2 ORDER SIZE GATE: %s below min notional $%.2f "
                                "(spendable=$%.2f)",
                                symbol,
                                _min_notional_floor,
                                _spendable_usd,
                            )
                            _trace("ecel", "rejected", f"below_min_notional_spendable:{_min_notional_floor:.2f}", terminal=True)
                            return None
                        logger.info(
                            "📈 Auto-adjusting size from $%.2f to $%.2f (minimum notional)",
                            position_size,
                            _min_notional_floor,
                        )
                        position_size = _min_notional_floor
                except Exception as _ng_exc:
                    logger.debug("Notional gate sizing skipped: %s", _ng_exc)
            elif position_size < MIN_NOTIONAL_USD:
                logger.warning(
                    "⛔ FIX2 ORDER SIZE GATE: %s order too small ($%.2f < $%.2f minimum)",
                    symbol,
                    position_size,
                    MIN_NOTIONAL_USD,
                )
                _trace("ecel", "rejected", f"order_below_min_notional:{position_size:.2f}", terminal=True)
                return None

            # ─── FIX 4: LIVE MODE ASSERTION ──────────────────────────────────────────
            # Re-read from env at call time so runtime env changes (BLOCK_EXECUTION=false,
            # DRY_RUN_MODE=false) set after module import take effect immediately.
            _dry_run_now = os.getenv("DRY_RUN_MODE", "false").lower() in ("true", "1", "yes")
            if _dry_run_now:
                logger.warning("⛔ FIX4 DRY_RUN_MODE=true — trade execution blocked for %s", symbol)
                _trace("ecel", "rejected", "dry_run_mode_enabled", terminal=True)
                return None

            # ✅ LAYER -1: CAPITAL INTEGRITY GATE (FIX 4)
            # Hard gate: block any trade if capital is insufficient or unavailable.
            # Must run before Recovery Controller and LIVE_CAPITAL_VERIFIED checks
            # so that a zero-capital state is caught before any further validation.
            if not self.can_execute_trade(position_size):
                logger.error(
                    "🚫 CAPITAL GATE BLOCKED ENTRY — Symbol: %s | Side: %s | Size: $%.2f "
                    "(can_execute_trade returned False — check balance/position limits)",
                    symbol,
                    side,
                    position_size,
                )
                _trace("ecel", "rejected", "capital_gate_blocked_entry", terminal=True)
                return None

            _regime = self._normalize_regime(take_profit_levels)
            _expectancy_bucket = self._build_expectancy_bucket_key(symbol, _regime)

            # ─── FIX 5: FORCE TRADE MODE — bypasses all downstream filters ─────────
            # Re-read from env so runtime changes take effect without restart.
            _force_trade_now = (
                os.getenv("FORCE_TRADE", "false").lower() in ("true", "1", "yes")
                or os.getenv("FORCE_TRADE_MODE", "false").lower() in ("true", "1", "yes")
            )
            if _force_trade_now or FORCE_TRADE_MODE:
                logger.warning(
                    "⚠️  FIX5 FORCE_TRADE_MODE=true — bypassing expectancy/edge/regime gates for %s",
                    symbol,
                )
            else:
                pass  # normal gate path continues below

            # Hard stop for buckets auto-disabled due to persistently negative expectancy.
            if self._is_expectancy_bucket_blocked(symbol, _expectancy_bucket):
                _until_ts = self._disabled_until.get(_expectancy_bucket)
                _remaining = None
                if _until_ts is not None:
                    _remaining = max(0, int((_until_ts - datetime.now()).total_seconds()))

                logger.warning(
                    "🚫 EXPECTANCY KILL-SWITCH: %s disabled (bucket=%s rolling expectancy below zero, remaining=%s)",
                    symbol,
                    _expectancy_bucket,
                    f"{_remaining}s" if _remaining is not None else "manual/legacy",
                )
                _trace("ecel", "rejected", f"expectancy_kill_switch:{_expectancy_bucket}", terminal=True)
                return None

            # ── PROOF-OF-TRADE: forced order sizing + critical attempt log ────────
            # Temporarily overrides position_size with a conservative forced size so
            # every execution path is exercised regardless of strategy signal quality.
            # Remove or gate behind a feature flag once live execution is verified.
            if CAPITAL_CSM_V2_AVAILABLE and get_csm_v2:
                try:
                    _csm = get_csm_v2()
                    _csm_status = _csm.status_dict()
                    _real_capital = _csm_status.get("real_capital") or 0.0
                    if _real_capital > 0:
                        # Micro-capital sizing: use 30% of real capital, no hard $5 cap.
                        # For $46.50 this yields $13.95 — enough to clear exchange minimums.
                        order_size = min(position_size, _real_capital * 0.30)
                        position_size = order_size
                        logger.critical(
                            f"ATTEMPTING TRADE: size={order_size:.4f} "
                            f"(real_capital=${_real_capital:.2f}, symbol={symbol}, side={side})"
                        )
                except Exception as _pot_err:
                    logger.warning(f"⚠️ Proof-of-trade sizing skipped: {_pot_err}")
            else:
                logger.critical(
                    f"ATTEMPTING TRADE: size={position_size:.4f} "
                    f"(CSM unavailable, symbol={symbol}, side={side})"
                )

            # ✅ LAYER 0: RECOVERY CONTROLLER - Capital-first safety layer
            # This is the AUTHORITATIVE control layer that sits above everything
            # Checks BEFORE any other validation
            if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
                recovery_controller = get_recovery_controller()
                can_trade, reason = recovery_controller.can_trade("entry")

                logger.critical(
                    "🛡️ [ExecutionEngine] RecoveryController gate | symbol=%s can_trade=%s "
                    "reason=%s state=%s capital_safety=%s",
                    symbol,
                    can_trade,
                    reason,
                    recovery_controller.current_state.value,
                    recovery_controller.capital_safety_level.value,
                )

                if not can_trade:
                    # ── FORCE_TRADE fallback: if RecoveryController still blocks despite
                    # the bypass in can_trade() itself (e.g. EMERGENCY_HALT), log and
                    # return None.  The bypass inside can_trade() handles all other states.
                    _rc_force_bypass = (
                        os.getenv("FORCE_TRADE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.getenv("FORCE_TRADE_MODE", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                        or os.getenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "").strip().lower()
                        in ("1", "true", "yes", "on", "enabled")
                    )
                    if _rc_force_bypass:
                        logger.critical(
                            "⚡ [ExecutionEngine] FORCE_TRADE: RecoveryController blocked %s %s "
                            "(reason=%s state=%s) — FORCE_TRADE active, proceeding to order submission.",
                            symbol, side, reason, recovery_controller.current_state.value,
                        )
                        # Fall through to order submission — do NOT return None.
                    else:
                        logger.error("=" * 80)
                        logger.error("🛡️  RECOVERY CONTROLLER BLOCKED ENTRY")
                        logger.error("=" * 80)
                        logger.error(f"   Symbol: {symbol}")
                        logger.error(f"   Side: {side}")
                        logger.error(f"   Position Size: ${position_size:.2f}")
                        logger.error(f"   Reason: {reason}")
                        logger.error(f"   Controller State: {recovery_controller.current_state.value}")
                        logger.error(f"   Capital Safety: {recovery_controller.capital_safety_level.value}")
                        logger.error("=" * 80)
                        _trace("ecel", "rejected", f"recovery_controller:{reason}", terminal=True)
                        return None
            
            # ✅ CRITICAL SAFETY CHECK #1: LIVE CAPITAL VERIFIED
            # This is the MASTER kill-switch that prevents accidental live trading
            # Check BEFORE any trade execution
            if HARD_CONTROLS_AVAILABLE and get_hard_controls:
                hard_controls = get_hard_controls()
                can_trade, error_msg = hard_controls.can_trade(self.user_id)

                logger.info(
                    "🔐 [ExecutionEngine] Hard controls gate | symbol=%s can_trade=%s reason=%s",
                    symbol,
                    can_trade,
                    error_msg or "ok",
                )

                if not can_trade:
                    # Allow bypass when NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK is set —
                    # consistent with how the execution pipeline handles this flag for
                    # single-instance Railway deployments without Redis fencing tokens.
                    _hc_bypass = (
                        os.getenv("FORCE_TRADE", "false").lower() in ("true", "1", "yes")
                        or os.getenv("FORCE_TRADE_MODE", "false").lower() in ("true", "1", "yes")
                        or os.getenv("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK", "false").lower() in ("true", "1", "yes", "on", "enabled")
                    )
                    if _hc_bypass:
                        logger.warning(
                            "⚠️  [ExecutionEngine] Hard controls block bypassed for %s — "
                            "FORCE_TRADE / FORCE_TRADE_MODE / NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK "
                            "is set. reason=%s",
                            symbol,
                            error_msg,
                        )
                    else:
                        logger.error("=" * 80)
                        logger.error("🔴 TRADE EXECUTION BLOCKED")
                        logger.error("=" * 80)
                        logger.error(f"   Symbol: {symbol}")
                        logger.error(f"   Side: {side}")
                        logger.error(f"   Position Size: ${position_size:.2f}")
                        logger.error(f"   User ID: {self.user_id}")
                        logger.error(f"   Reason: {error_msg}")
                        logger.error(f"   Tip: Set LIVE_CAPITAL_VERIFIED=true, FORCE_TRADE=true, or")
                        logger.error(f"        NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true to enable trading.")
                        logger.error("=" * 80)
                        _trace("ecel", "rejected", f"hard_controls:{error_msg}", terminal=True)
                        return None

            # FIX #3 (Jan 19, 2026): Check if broker supports this symbol before attempting trade
            if self.broker_client and hasattr(self.broker_client, 'supports_symbol'):
                if not self.broker_client.supports_symbol(symbol):
                    broker_name_str = resolve_broker_label(self.broker_client)
                    logger.info(f"   ❌ Entry rejected for {symbol}")
                    logger.info(f"      Reason: {broker_name_str.title()} does not support this symbol")
                    logger.info(f"      💡 This symbol may be specific to another exchange (e.g., BUSD is Binance-only)")
                    _trace("ecel", "rejected", "symbol_not_supported_by_broker", terminal=True)
                    return None

            # Log entry attempt
            logger.info(f"Executing {side} entry: {symbol} size=${position_size:.2f}")
            logger.info(
                "✅ SIGNAL GENERATED: symbol=%s side=%s requested_size=$%.2f",
                symbol,
                side,
                position_size,
            )

            # ── HARD MINIMUM ORDER FILTER ─────────────────────────────────────
            # Unconditional guard: rejects sub-minimum orders before any further
            # processing.  Prevents broker rejections, wasted API cycles, and
            # log noise regardless of whether the notional-gate module loaded.
            # Values intentionally inlined (not imported from strategy) so this
            # backstop remains self-contained even if other modules fail to load.
            # Keep in sync with BROKER_MIN_ORDER_USD in nija_apex_strategy_v71.py.
            _HARD_MIN_BY_BROKER = {
                'coinbase': max(EXCHANGE_HARD_FLOOR_USD, MIN_TRADE_USD),
                'kraken':   max(float(os.getenv('KRAKEN_MIN_NOTIONAL_USD', str(MIN_TRADE_USD))), MIN_TRADE_USD),
                'binance':  10.0,   # Binance MIN_NOTIONAL filter (USDT pairs)
                'okx':      10.0,   # OKX operational floor
                'alpaca':    1.0,   # Alpaca — commission-free, no practical minimum
            }
            _hard_broker_key = ''
            if self.broker_client and hasattr(self.broker_client, 'broker_type'):
                _bt = self.broker_client.broker_type
                _hard_broker_key = (
                    _bt.value if hasattr(_bt, 'value') else str(_bt)
                ).lower()
            _hard_min = (
                _min_notional_floor
                if _min_notional_floor is not None
                else _HARD_MIN_BY_BROKER.get(_hard_broker_key, max(EXCHANGE_HARD_FLOOR_USD, MIN_TRADE_USD))
            )
            _hard_min = self._apply_exchange_floor(_hard_min)

            # Reserve a spendable cash buffer to avoid precision/fee insufficient-funds rejects.
            if _spendable_usd is not None and position_size > _spendable_usd:
                logger.info(
                    "🔒 Spendable-balance cap: requested $%.2f -> $%.2f (available=$%.2f, buffer=%.1f%%)",
                    position_size,
                    _spendable_usd,
                    _available_usd or 0.0,
                    BALANCE_BUFFER_PCT * 100.0,
                )
                position_size = _spendable_usd

            # Optional one-shot probe trade to validate end-to-end execution plumbing.
            if FORCE_FIRST_TRADE and FORCE_TRADE_ON_FIRST_VALID_SIGNAL and not self._force_first_trade_done:
                _probe_size = max(MIN_TRADE_USD, FORCE_TRADE_NOTIONAL)
                logger.warning(
                    "🧪 FORCE_FIRST_TRADE armed: overriding order size to $%.2f for first valid signal",
                    _probe_size,
                )
                position_size = _probe_size

            if position_size < _hard_min:
                if _spendable_usd is not None and _hard_min <= _spendable_usd:
                    logger.info(
                        "📈 Auto-adjusting size from $%.2f to $%.2f (hard minimum)",
                        position_size,
                        _hard_min,
                    )
                    position_size = _hard_min
                else:
                    logger.warning(
                        f"Trade skipped: size ${position_size:.2f} < min ${_hard_min:.2f} "
                        f"for {symbol} ({_hard_broker_key or 'broker'})"
                    )
                    _trace("ecel", "rejected", f"hard_min_notional:{position_size:.2f}<{_hard_min:.2f}", terminal=True)
                    return None

            # ✅ Exchange constraints enforcer — adjust or reject before broker submission
            if EXCHANGE_CONSTRAINTS_AVAILABLE and validate_order_constraints and entry_price > 0:
                try:
                    _constraint = validate_order_constraints(
                        symbol=symbol,
                        order_size_usd=position_size,
                        price_usd=entry_price,
                        broker_type=_hard_broker_key or broker_label,
                    )
                    if not _constraint.is_valid:
                        _recommended = _constraint.recommended_size_usd or _constraint.min_required_usd
                        if _recommended and (_spendable_usd is None or _recommended <= _spendable_usd):
                            logger.info(
                                "📏 Exchange constraint resize: $%.2f → $%.2f (%s)",
                                position_size,
                                _recommended,
                                _constraint.reason,
                            )
                            position_size = _recommended
                        else:
                            logger.warning(
                                "🚫 EXCHANGE CONSTRAINT REJECT: %s (size=$%.2f)",
                                _constraint.reason,
                                position_size,
                            )
                            _trace("ecel", "rejected", f"exchange_constraints:{_constraint.reason}", terminal=True)
                            return None
                except Exception as _constraint_exc:
                    logger.debug("Exchange constraint validation skipped: %s", _constraint_exc)

            logger.info(
                "✅ TRADE APPROVED: symbol=%s side=%s size=$%.2f broker=%s",
                symbol,
                side,
                position_size,
                (_hard_broker_key or 'unknown').upper(),
            )

            # ✅ ENHANCEMENT #1: MINIMUM NOTIONAL GATE
            # Check if entry size meets minimum notional requirements
            broker_name = None
            if self.broker_client and hasattr(self.broker_client, 'broker_type'):
                broker_name = resolve_broker_label(self.broker_client)

            position_size, rejection_reason = self._apply_minimum_notional_gate(
                symbol=symbol,
                position_size=position_size,
                broker_name=broker_name,
                balance_usd=_available_usd or 0.0,
                affordable_usd=_spendable_usd if _spendable_usd is not None else _available_usd,
            )
            if position_size is None:
                logger.warning(f"❌ Entry rejected: {rejection_reason}")
                _trace("ecel", "rejected", f"minimum_notional_gate:{rejection_reason}", terminal=True)
                return None

            # ✅ NET EDGE GATE: Reject trades that cannot clear the minimum
            # profitability threshold after fees, slippage, and spread.
            # Dynamic fee detection: pull live rates from the broker when
            # available, otherwise fall back to hardcoded broker defaults.
            tp1_price = take_profit_levels.get('tp1', 0.0)
            if entry_price > 0 and tp1_price > 0:
                # Market quality skip-cycle gate to avoid always-on trading.
                _market_quality = float(take_profit_levels.get('market_quality', 1.0) or 1.0)
                if not FORCE_TRADE_MODE and _market_quality < MARKET_QUALITY_THRESHOLD:
                    logger.info(
                        "⏭️ MARKET QUALITY GATE: skipping %s | quality=%.3f < %.3f",
                        symbol,
                        _market_quality,
                        MARKET_QUALITY_THRESHOLD,
                    )
                    _trace("ecel", "rejected", f"market_quality_gate:{_market_quality:.3f}", terminal=True)
                    return None

                # Regime-specific suppression and threshold tuning.
                if not FORCE_TRADE_MODE and _regime in {"low_vol", "low_volatility", "dead", "chop"}:
                    logger.info("⏭️ REGIME GATE: skipping %s due to low-opportunity regime (%s)", symbol, _regime)
                    _trace("ecel", "rejected", f"regime_gate:{_regime}", terminal=True)
                    return None

                _regime_expectancy_floor = MIN_EXPECTANCY_THRESHOLD_PCT
                if _regime in {"high_vol", "high_volatility", "volatile"}:
                    _regime_expectancy_floor = max(_regime_expectancy_floor, 0.0005)

                # --- Fetch fees (dynamic first, then hardcoded fallback) ---
                _live_fees = None
                if self.broker_client and hasattr(self.broker_client, 'get_trading_fees'):
                    try:
                        _live_fees = self.broker_client.get_trading_fees(symbol)
                    except Exception:
                        pass

                if _live_fees and _live_fees.get('taker_fee'):
                    _fee_rate = float(_live_fees['taker_fee'])
                    _fee_source = _live_fees.get('source', 'live')
                else:
                    _fee_rate = self._get_broker_round_trip_fee() / 2  # one-way from round-trip
                    _fee_source = 'hardcoded'

                # Conservative cost assumptions
                _slippage_rate = 0.001   # 0.1% slippage
                _spread_rate = 0.001     # 0.1% spread

                # Side-aware win geometry so both long and short paths are gated.
                if side == 'short':
                    _reward_move = (entry_price - tp1_price) / entry_price
                else:
                    _reward_move = (tp1_price - entry_price) / entry_price

                if not FORCE_TRADE_MODE and not trade_is_economical(
                    position_size,
                    max(0.0, _reward_move),
                    fee_rate=_fee_rate,
                    min_edge_multiplier=MIN_EDGE_MULTIPLIER,
                ):
                    logger.warning(
                        "🚫 REJECT_FEE_DOMINATED: %s size=$%.2f expected_edge=%.4f%% fee_rate=%.4f%% multiplier=%.2f",
                        symbol,
                        position_size,
                        max(0.0, _reward_move) * 100.0,
                        _fee_rate * 100.0,
                        MIN_EDGE_MULTIPLIER,
                    )
                    _trace("ecel", "rejected", "fee_dominated_trade", terminal=True)
                    return None

                _total_cost_rate = (_fee_rate * 2) + _slippage_rate + _spread_rate
                _gross_win_usd = position_size * _reward_move
                _win_costs_usd = position_size * _total_cost_rate
                _net_edge = _gross_win_usd - _win_costs_usd
                _net_edge_pct = _net_edge / position_size if position_size > 0 else 0.0

                if not FORCE_TRADE_MODE and _net_edge_pct < MIN_EDGE_THRESHOLD:
                    logger.warning("=" * 70)
                    logger.warning("🚫 NET EDGE GATE: Trade rejected — insufficient net profit")
                    logger.warning("=" * 70)
                    logger.warning(f"   Symbol:          {symbol}")
                    logger.warning(f"   Entry:           ${entry_price:.4f}")
                    logger.warning(f"   TP1 Target:      ${tp1_price:.4f}")
                    logger.warning(f"   Position Size:   ${position_size:.2f}")
                    logger.warning(f"   Fee Rate (1-way):{_fee_rate*100:.3f}% [{_fee_source}]")
                    logger.warning(f"   Net Edge:        {_net_edge_pct*100:.4f}% "
                                   f"(min required: {MIN_EDGE_THRESHOLD*100:.2f}%)")
                    logger.warning("=" * 70)
                    _trace("ecel", "rejected", f"net_edge_gate:{_net_edge_pct:.6f}", terminal=True)
                    return None

                logger.info(f"✅ Net Edge Gate passed: {_net_edge_pct*100:.4f}% "
                            f">= {MIN_EDGE_THRESHOLD*100:.2f}% threshold "
                            f"[fees: {_fee_source}]")

                # Minimum target geometry gate (TP and SL sanity).
                _reward_move = abs(_reward_move)
                _risk_move = abs((entry_price - stop_loss) / entry_price)
                if _reward_move < MIN_TP_PCT:
                    logger.warning(
                        "🚫 TARGET GEOMETRY GATE: %s TP too small (%.3f%% < %.3f%%)",
                        symbol,
                        _reward_move * 100.0,
                        MIN_TP_PCT * 100.0,
                    )
                    _trace("ecel", "rejected", "target_geometry_tp_too_small", terminal=True)
                    return None
                if _risk_move > MAX_SL_PCT:
                    logger.warning(
                        "🚫 TARGET GEOMETRY GATE: %s SL too wide (%.3f%% > %.3f%%)",
                        symbol,
                        _risk_move * 100.0,
                        MAX_SL_PCT * 100.0,
                    )
                    _trace("ecel", "rejected", "target_geometry_sl_too_wide", terminal=True)
                    return None

                # ✅ POSITIVE EXPECTANCY GATE (E > 0)
                # Expected value per trade must be positive after estimated costs:
                #   E = p(win)*net_win - (1-p(win))*net_loss
                # where net_win is TP1 net edge and net_loss includes stop-loss move
                # plus round-trip execution costs.
                _p_win = self._resolve_expected_win_rate(take_profit_levels)
                _gross_loss_usd = position_size * _risk_move
                _loss_costs_usd = position_size * ((_fee_rate * 2) + _slippage_rate + _spread_rate)
                _net_loss_usd = _gross_loss_usd + _loss_costs_usd

                _expectancy_usd = (_p_win * _net_edge) - ((1.0 - _p_win) * _net_loss_usd)
                _expectancy_pct = (_expectancy_usd / position_size) if position_size > 0 else -1.0

                # Unified edge score (expected profitability score).
                _reward_risk = (_reward_move / _risk_move) if _risk_move > 0 else 0.0
                _cost_penalty = (_fee_rate * 2) + _slippage_rate + _spread_rate
                _edge_score = self._compute_edge_score(_p_win, _reward_risk, _cost_penalty)

                # Breakeven win-rate implied by this R/R + cost profile.
                _denom = (_net_edge + _net_loss_usd)
                _breakeven_win_rate = (_net_loss_usd / _denom) if _denom > 0 else 1.0

                if not FORCE_TRADE_MODE and _edge_score <= MIN_EDGE_SCORE_THRESHOLD:
                    logger.warning("=" * 70)
                    logger.warning("🚫 EDGE SCORE GATE: Trade rejected — weak expected profitability")
                    logger.warning("=" * 70)
                    logger.warning(f"   Symbol:                {symbol}")
                    logger.warning(f"   Regime:                {_regime or 'unspecified'}")
                    logger.warning(f"   Reward/Risk:           {_reward_risk:.4f}")
                    logger.warning(f"   Cost Penalty:          {_cost_penalty*100:.4f}%")
                    logger.warning(f"   Edge Score:            {_edge_score:.6f} (min {MIN_EDGE_SCORE_THRESHOLD:.6f})")
                    logger.warning("=" * 70)
                    _trace("ecel", "rejected", f"edge_score_gate:{_edge_score:.6f}", terminal=True)
                    return None

                if not FORCE_TRADE_MODE and _expectancy_pct <= _regime_expectancy_floor:
                    logger.warning("=" * 70)
                    logger.warning("🚫 EXPECTANCY GATE: Trade rejected — non-positive expectancy")
                    logger.warning("=" * 70)
                    logger.warning(f"   Symbol:                {symbol}")
                    logger.warning(f"   Regime:                {_regime or 'unspecified'}")
                    logger.warning(f"   Expected Win Rate:     {_p_win*100:.2f}%")
                    logger.warning(f"   Breakeven Win Rate:    {_breakeven_win_rate*100:.2f}%")
                    logger.warning(f"   Net Win (TP1):         ${_net_edge:.2f}")
                    logger.warning(f"   Net Loss (SL+costs):   ${_net_loss_usd:.2f}")
                    logger.warning(f"   Expectancy:            ${_expectancy_usd:.2f} ({_expectancy_pct*100:.4f}%)")
                    logger.warning(f"   Required Floor:        {_regime_expectancy_floor*100:.4f}%")
                    logger.warning("=" * 70)
                    _trace("ecel", "rejected", f"expectancy_gate:{_expectancy_pct:.6f}", terminal=True)
                    return None

                # Kelly-lite sizing clamp to avoid oversized allocations.
                _kelly_fraction = self._compute_kelly_fraction(_p_win, _reward_risk)
                if _kelly_fraction <= 0 and not FORCE_TRADE_MODE:
                    logger.warning(
                        "🚫 KELLY GATE: %s rejected (kelly fraction <= 0; p_win=%.2f%%, rr=%.3f)",
                        symbol,
                        _p_win * 100.0,
                        _reward_risk,
                    )
                    _trace("ecel", "rejected", "kelly_gate_non_positive", terminal=True)
                    return None
                # In FORCE_TRADE_MODE, clamp kelly to 1.0 so sizing is unchanged
                if _kelly_fraction <= 0:
                    _kelly_fraction = 1.0

                _pre_kelly_size = position_size
                position_size = max(position_size * _kelly_fraction, 0.0)
                if position_size <= 0:
                    logger.warning("🚫 KELLY GATE: %s rejected (post-kelly size is zero)", symbol)
                    _trace("ecel", "rejected", "kelly_gate_zero_size", terminal=True)
                    return None

                logger.info(
                    "✅ Expectancy/Edge Gate passed: E=$%.2f (%.4f%%), edge_score=%.6f, p_win=%.2f%%, breakeven=%.2f%%, kelly=%.3f, size $%.2f->$%.2f",
                    _expectancy_usd,
                    _expectancy_pct * 100.0,
                    _edge_score,
                    _p_win * 100.0,
                    _breakeven_win_rate * 100.0,
                    _kelly_fraction,
                    _pre_kelly_size,
                    position_size,
                )


            execution_plan = self._optimize_execution_with_intelligence(
                symbol=symbol,
                side=side,
                size_usd=position_size,
                urgency=0.7  # Default to moderate urgency for entries
            )

            # Place order via broker client (order type determined by execution plan)
            if self.broker_client:
                order_side = 'buy' if side == 'long' else 'sell'

                # Log canonical broker identity for this trade
                broker_name_str = format_broker_identity(self.broker_client)

                # Allow ops to keep Coinbase connected for data while disabling execution.
                # Default is "true" — Coinbase trading is ENABLED unless explicitly set to false.
                _coinbase_exec_disabled = os.getenv("ENABLE_COINBASE_TRADING", "true").strip().lower() in (
                    "0", "false", "no", "off"
                )
                if broker_name_str.lower() == "coinbase" and _coinbase_exec_disabled:
                    logger.error(
                        "🚫 COINBASE_EXECUTION_DISABLED: order dropped for %s %s — "
                        "ENABLE_COINBASE_TRADING is set to a falsy value. "
                        "Set ENABLE_COINBASE_TRADING=true to enable Coinbase order submission.",
                        order_side,
                        symbol,
                    )
                    _trace("ecel", "rejected", "coinbase_execution_disabled", terminal=True)
                    return None
                # ─── FIX 6: MANDATORY PRE-EXECUTION LOG ──────────────────────────
                _pfunnel("risk_passed")
                logger.critical(
                    "🚀 EXECUTING TRADE: %s | side=%s | size=$%.2f | entry=$%.4f | broker=%s",
                    symbol, side, position_size, entry_price, broker_name_str.upper(),
                )
                logger.info(f"   Using broker: {broker_name_str.upper()}")

                # Dynamic order type: use limit when the execution plan recommends it
                # and the broker supports place_limit_order.  Falls back to market on
                # any failure so entries are never silently skipped.
                _use_limit = (
                    execution_plan is not None
                    and EXECUTION_INTELLIGENCE_AVAILABLE
                    and execution_plan.order_type == EIOrderType.LIMIT
                    and execution_plan.limit_price is not None
                    and execution_plan.limit_price > 0
                    and hasattr(self.broker_client, 'place_limit_order')
                )

                if _use_limit:
                    _limit_price = execution_plan.limit_price
                    # Guard against pathologically small prices that would produce
                    # an astronomically large base quantity.
                    if _limit_price < 1e-8:
                        logger.warning(
                            f"   ⚠️ Limit price ${_limit_price} too small for {symbol}, "
                            f"falling back to market order"
                        )
                        _use_limit = False

                    if _use_limit:
                        _limit_price = execution_plan.limit_price
                        logger.info(
                            f"   📊 Dynamic order type: LIMIT @ ${_limit_price:.6f} "
                            f"(liquidity/volatility-driven, ECEL will compile qty)"
                        )
                        _limit_qty = position_size / _limit_price if _limit_price > 0 else 0.0
                        logger.critical(
                            "ORDER ATTEMPT | symbol=%s side=%s qty=%s notional=$%.2f",
                            symbol,
                            order_side,
                            f"{_limit_qty:.8f}",
                            position_size,
                        )
                        _entry_t0 = _time.monotonic()
                        _entry_exc: Optional[Exception] = None
                        _pfunnel("execution_attempted")
                        try:
                            result = self._submit_limit_order_via_ecel(
                                broker_client=self.broker_client,
                                symbol=symbol,
                                side=order_side,
                                size_usd=position_size,
                                limit_price=_limit_price,
                                available_balance_usd=_available_usd,
                                spendable_balance_usd=_spendable_usd,
                                strategy_name=strategy_name if hasattr(self, "_strategy_name") else "ExecutionEngine",
                            )
                        except Exception as _limit_exc:
                            logger.warning(
                                f"   ⚠️ Limit order raised exception for {symbol}: {_limit_exc}, "
                                f"falling back to market order"
                            )
                            _entry_exc = _limit_exc
                            result = None
                        # Emit result for the limit attempt (before fallback)
                        self._emit_execution_result(symbol, order_side, result, _entry_t0, _entry_exc)
                        _ecel_limit_status = self._normalized_order_status(result)
                        if result is None or _ecel_limit_status in {'error', 'unfilled', 'skipped', 'rejected'}:
                            _trace("ecel", "rejected", f"limit_order_rejected:{_ecel_limit_status}", extra={"order_type": "limit"})
                        else:
                            _trace("ecel", "pass", "limit_order_compiled", extra={"order_type": "limit"})
                        # If the limit order fails or errors, fall back to a market order
                        if result is None or self._normalized_order_status(result) in {'error', 'unfilled', 'skipped', 'rejected'}:
                            logger.warning(
                                f"   ⚠️ Limit order failed for {symbol}, "
                                f"falling back to market order"
                            )
                            _entry_t0 = _time.monotonic()
                            _fallback_exc: Optional[Exception] = None
                            try:
                                _fallback_qty = position_size / entry_price if entry_price > 0 else 0.0
                                logger.critical(
                                    "ORDER ATTEMPT | symbol=%s side=%s qty=%s notional=$%.2f",
                                    symbol,
                                    order_side,
                                    f"{_fallback_qty:.8f}",
                                    position_size,
                                )
                                result = self._submit_market_order_via_pipeline(
                                    broker_client=self.broker_client,
                                    symbol=symbol,
                                    side=order_side,
                                    size_usd=position_size,
                                    available_balance_usd=_spendable_usd or _available_usd,
                                    price_hint_usd=entry_price,
                                )
                            except Exception as _fb_exc:
                                _fallback_exc = _fb_exc
                                result = None
                            self._emit_execution_result(symbol, order_side, result, _entry_t0, _fallback_exc)
                            _ecel_fb_status = self._normalized_order_status(result)
                            if result is None or _ecel_fb_status in {'error', 'unfilled', 'skipped', 'rejected'}:
                                _trace("ecel", "rejected", f"fallback_market_rejected:{_ecel_fb_status}", terminal=True, extra={"order_type": "market"})
                            else:
                                _trace("ecel", "pass", "fallback_market_compiled", extra={"order_type": "market"})
                            if _fallback_exc is not None:
                                raise _fallback_exc
                else:
                    # Determine why market order is being used for the log message
                    if execution_plan is None:
                        _order_reason = "no execution plan available"
                    elif execution_plan.order_type != EIOrderType.LIMIT:
                        _order_reason = f"plan recommends {execution_plan.order_type.value}"
                    else:
                        _order_reason = "broker does not support limit orders"
                    logger.info(f"   📊 Dynamic order type: MARKET ({_order_reason})")

                    # ✅ EXCHANGE ORDER COMPILER: Final authority before broker placement
                    # Pre-hoc canonicalization: constraints → sizing → simulation → approval
                    _broker_name = "unknown"
                    if self.broker_client and hasattr(self.broker_client, "broker_type"):
                        _broker_name = resolve_broker_label(self.broker_client)

                    _compiled_order = None
                    _pricing_snapshot_cls = PricingSnapshot
                    if EXCHANGE_ORDER_COMPILER_AVAILABLE and _eoc and isinstance(_pricing_snapshot_cls, type):
                        try:
                            # Use cached balance snapshot (no exchange polling)
                            _available_balance = float(_available_usd or 0.0)

                            # Build pricing snapshot
                            _pricing = _pricing_snapshot_cls(
                                symbol=symbol,
                                bid=entry_price * 0.999,  # Conservative bid (0.1% lower)
                                ask=entry_price * 1.001,   # Conservative ask (0.1% higher)
                                mid=entry_price,
                                available_balance_usd=_available_balance,
                            )

                            # Compile order through all four gates
                            _compiled_order = _eoc.compile(
                                symbol=symbol,
                                side="buy" if side == "long" else "sell",
                                size_usd=position_size,
                                pricing=_pricing,
                                exchange=_broker_name,
                                min_profit_threshold_usd=5.0,  # Minimum $5 profit
                            )
                            logger.info(
                                "[EOC] ✅ Order compiled successfully: %s",
                                _compiled_order,
                            )
                        except Exception as _eoc_exc:
                            if isinstance(OrderCompileError, type) and isinstance(_eoc_exc, OrderCompileError):
                                logger.error(
                                    "[EOC] ❌ ORDER COMPILATION FAILED: %s — trade REJECTED",
                                    _eoc_exc,
                                )
                                _trace("ecel", "rejected", f"exchange_order_compiler:{_eoc_exc}", terminal=True)
                                return None
                            logger.warning(
                                "[EOC] Warning: order compilation exception: %s — using fallback",
                                _eoc_exc,
                            )

                    # Use compiled quantity if available, else fallback
                    if _compiled_order:
                        _order_quantity = _compiled_order.quantity
                        _order_size_usd = _compiled_order.size_usd
                    else:
                        # Fallback: simple calculation (less safe)
                        _order_size_usd = position_size
                        _order_quantity = position_size / entry_price if entry_price > 0 else 0.0

                        # Explicitly floor quantity to exchange step size before submission
                        # to avoid precision drift causing false insufficient-funds rejects.
                        try:
                            if EXCHANGE_ORDER_COMPILER_AVAILABLE and _eoc:
                                _constraints = _eoc.get_constraints(_broker_name, symbol)
                                _step = float(getattr(_constraints, "step_size", 0.0) or 0.0)
                                if _step > 0.0:
                                    _order_quantity = (_order_quantity // _step) * _step
                                    _order_size_usd = _order_quantity * entry_price
                        except Exception:
                            pass

                        if _order_size_usd < MIN_TRADE_USD:
                            logger.info(
                                "⏭️  REJECT_BELOW_MIN: %s order_notional=$%.2f < MIN_TRADE_USD=$%.2f",
                                symbol,
                                _order_size_usd,
                                MIN_TRADE_USD,
                            )
                            _trace("ecel", "rejected", f"order_notional_below_min:{_order_size_usd:.2f}", terminal=True)
                            return None

                    _entry_t0 = _time.monotonic()
                    _market_exc: Optional[Exception] = None
                    _pfunnel("execution_attempted")
                    logger.critical(
                        "ORDER ATTEMPT | symbol=%s side=%s qty=%s notional=$%.2f",
                        symbol,
                        order_side,
                        f"{_order_quantity:.8f}",
                        _order_size_usd,
                    )
                    # Use the state-machine controller so taxonomy-driven retry /
                    # halt logic is handled in one place instead of scattered
                    # if/elif policy branches.
                    if _EXEC_STATE_CONTROLLER_AVAILABLE and _ExecutionStateController is not None:
                        _mkt_ctrl = _ExecutionStateController()
                        _exec_result = _mkt_ctrl.submit(
                            symbol=symbol,
                            side=order_side,
                            qty=_order_size_usd,
                            broker_fn=lambda: self._submit_market_order_via_pipeline(
                                broker_client=self.broker_client,
                                symbol=symbol,
                                side=order_side,
                                size_usd=_order_size_usd,
                                available_balance_usd=_spendable_usd or _available_usd,
                                price_hint_usd=entry_price,
                            ),
                        )
                        result = _mkt_ctrl.last_broker_response
                        _market_exc = _mkt_ctrl.last_exception
                        if _exec_result is not None and callable(_log_exec_result):
                            _log_exec_result(_exec_result)
                        self._execution_controller = _mkt_ctrl
                    else:
                        try:
                            result = self._submit_market_order_via_pipeline(
                                broker_client=self.broker_client,
                                symbol=symbol,
                                side=order_side,
                                size_usd=_order_size_usd,
                                available_balance_usd=_spendable_usd or _available_usd,
                                price_hint_usd=entry_price,
                            )
                        except Exception as _mk_exc:
                            _market_exc = _mk_exc
                            result = None
                        self._emit_execution_result(symbol, order_side, result, _entry_t0, _market_exc)
                    _ecel_market_status = self._normalized_order_status(result)
                    if result is None or _ecel_market_status in {'error', 'unfilled', 'skipped', 'rejected'}:
                        _trace("ecel", "rejected", f"market_order_rejected:{_ecel_market_status}", terminal=True, extra={"order_type": "market"})
                    else:
                        _trace("ecel", "pass", "market_order_compiled", extra={"order_type": "market"})
                    if _market_exc is not None:
                        raise _market_exc

                # Post-submit fill confirmation (when order_id is available)
                if result:
                    # position_size is USD notional; dividing by entry_price yields base-asset quantity.
                    _expected_quantity = position_size / entry_price if entry_price > 0 else 0.0
                    if entry_price > 0 and _expected_quantity / max(position_size, MIN_POSITION_SIZE_EPSILON) > LARGE_QUANTITY_RATIO_THRESHOLD:
                        logger.debug(
                            "Large expected quantity computed for %s: %.6g (entry_price=%.8f)",
                            symbol,
                            _expected_quantity,
                            entry_price,
                        )
                    result = self._confirm_order_fill(symbol, order_side, _expected_quantity, result)

                # ─── FIX 6: MANDATORY POST-EXECUTION LOG ─────────────────────────
                _result_status_log = result.get('status', 'N/A') if result else 'NONE'
                if result and _result_status_log not in ('error', 'unfilled', 'skipped', 'rejected'):
                    logger.critical(
                        "✅ ORDER SENT SUCCESSFULLY: %s | side=%s | size=$%.2f | status=%s | order_id=%s",
                        symbol, side, position_size,
                        _result_status_log,
                        result.get('order_id') or result.get('id', 'N/A'),
                    )
                    logger.info(
                        "✅ ORDER SUBMITTED: symbol=%s side=%s status=%s order_id=%s",
                        symbol,
                        side,
                        _result_status_log,
                        result.get('order_id') or result.get('id', 'N/A'),
                    )
                else:
                    logger.critical(
                        "❌ ORDER FAILED: %s | side=%s | size=$%.2f | status=%s",
                        symbol, side, position_size, _result_status_log,
                    )
                logger.debug(f"   Order result status: {_result_status_log}")

                # ✅ SAFETY CHECK #2: Hard-stop on rejected orders
                # DO NOT record trade if order failed or was rejected
                result_status = self._normalized_order_status(result)

                if result_status == 'nonce_skip':
                    logger.warning("⚠️  Nonce pause active — skipping cycle, will retry next scan")
                    logger.warning(f"   Symbol: {symbol}, Size: ${position_size:.2f}")
                    _trace("broker", "rejected", "nonce_skip", terminal=True)
                    return None

                if result_status == 'error':
                    details = self._extract_order_failure_details(broker_response=result)
                    self._log_order_failure(symbol, position_size, broker_response=result)

                    # Check if this is a geographic restriction and add to blacklist
                    self._handle_geographic_restriction_error(symbol, details['detail'])
                    _trace("broker", "rejected", details.get('detail', 'broker_error'), terminal=True)

                    return None

                # Check for 'unfilled' status which indicates order wasn't placed
                if result_status == 'unfilled':
                    self._log_order_failure(symbol, position_size, broker_response=result)
                    _trace("broker", "rejected", "unfilled", terminal=True)
                    return None

                if result_status == 'skipped':
                    self._log_order_failure(symbol, position_size, broker_response=result)
                    _trace("broker", "rejected", "skipped", terminal=True)
                    return None

                # ✅ SAFETY CHECK #3: Require txid before recording position
                # Verify order has a valid transaction ID
                order_id = result.get('order_id') or result.get('id')
                if not order_id:
                    logger.error("=" * 70)
                    logger.error("❌ NO TXID - CANNOT RECORD POSITION")
                    logger.error("=" * 70)
                    logger.error(f"   Symbol: {symbol}, Side: {side}")
                    logger.error(f"   Position Size: ${position_size:.2f}")
                    logger.error("   ⚠️  Order must have valid txid before recording position")
                    logger.error("=" * 70)
                    _trace("broker", "rejected", "missing_order_id", terminal=True)
                    return None

                # ✅ REQUIREMENT: Confirm status=open or closed
                # BLOCK ledger writes until order status is confirmed
                order_status = self._normalized_order_status(result)
                if order_status not in VALID_ORDER_STATUSES:
                    logger.error(LOG_SEPARATOR)
                    logger.error("❌ INVALID ORDER STATUS - CANNOT RECORD POSITION")
                    logger.error(LOG_SEPARATOR)
                    logger.error(f"   Symbol: {symbol}, Side: {side}")
                    logger.error(f"   Order ID: {order_id}")
                    logger.error(f"   Status: {order_status} (expected: {'/'.join(VALID_ORDER_STATUSES)})")
                    logger.error("   ⚠️  Order status must be confirmed before recording position")
                    logger.error(LOG_SEPARATOR)
                    _trace("broker", "rejected", f"invalid_order_status:{order_status}", terminal=True)
                    return None

                _trace("broker", "pass", "order_accepted", extra={"order_id": str(order_id), "status": order_status})
                _pfunnel("orders_routed")

                if FORCE_FIRST_TRADE and FORCE_TRADE_ON_FIRST_VALID_SIGNAL and not self._force_first_trade_done:
                    self._force_first_trade_done = True
                    logger.warning("✅ FORCE_FIRST_TRADE completed — auto-disabling probe mode for this process")

                # CRITICAL: Validate filled price to prevent accepting immediate losers
                # Extract actual fill price from order result
                actual_fill_price = self._extract_fill_price(result, symbol)

                # ✅ SAFETY CHECK #4: Kill zero-price fills immediately
                # Validate that fill price is valid (> 0)
                if actual_fill_price is not None and actual_fill_price <= 0:
                    logger.error("=" * 70)
                    logger.error("❌ INVALID FILL PRICE - CANNOT RECORD POSITION")
                    logger.error("=" * 70)
                    logger.error(f"   Symbol: {symbol}, Side: {side}")
                    logger.error(f"   Fill Price: {actual_fill_price} (INVALID)")
                    logger.error("   ⚠️  Price must be greater than zero")
                    logger.error("=" * 70)
                    _trace("fill", "rejected", "invalid_fill_price", terminal=True)
                    return None

                # Validate immediate P&L to reject bad fills
                if actual_fill_price and not self._validate_entry_price(
                    symbol=symbol,
                    side=side,
                    expected_price=entry_price,
                    actual_price=actual_fill_price,
                    position_size=position_size
                ):
                    # Position rejected - it was immediately closed by validation
                    self.rejected_trades_count += 1
                    _trace("fill", "rejected", "entry_price_validation_failed", terminal=True)
                    return None

                # Use actual fill price if available, otherwise use expected
                final_entry_price = actual_fill_price if actual_fill_price else entry_price

                # Calculate quantity from position size
                quantity = position_size / final_entry_price

                # Calculate entry fee (assuming 0.6% taker fee)
                entry_fee = position_size * 0.006

                # ✅ MASTER TRADE VERIFICATION: Capture required data
                # Extract fill_time from result (use timestamp field or current time)
                fill_time = result.get('timestamp') or datetime.now()

                # Extract filled_volume from result
                filled_volume = result.get('filled_volume', quantity)

                # Calculate executed_cost: filled_price * filled_volume + fees
                executed_cost = (final_entry_price * filled_volume) + entry_fee

                # Log platform trade verification data
                logger.info(LOG_SEPARATOR)
                logger.info("✅ PLATFORM TRADE VERIFICATION")
                logger.info(LOG_SEPARATOR)
                logger.info(f"   Kraken Order ID: {order_id}")
                logger.info(f"   Fill Time: {fill_time}")
                logger.info(f"   Executed Cost: ${executed_cost:.2f}")
                logger.info(f"   Fill Price: ${final_entry_price:.2f}")
                logger.info(f"   Filled Volume: {filled_volume:.8f}")
                logger.info(f"   Entry Fee: ${entry_fee:.2f}")
                logger.info(f"   Order Status: {order_status}")
                logger.info(LOG_SEPARATOR)

                # Generate unique position ID
                position_id = f"{symbol}_{int(datetime.now().timestamp())}"

                # Record BUY/SELL in trade ledger database
                if self.trade_ledger:
                    try:
                        # Use the already validated order_id from safety check #3
                        # Include master trade verification data in notes
                        verification_notes = (
                            f"{side.upper()} entry | "
                            f"Order ID: {order_id} | "
                            f"Fill Time: {fill_time} | "
                            f"Executed Cost: ${executed_cost:.2f} | "
                            f"Status: {order_status}"
                        )

                        self.trade_ledger.record_buy(
                            symbol=symbol,
                            price=final_entry_price,
                            quantity=filled_volume,
                            size_usd=position_size,
                            fee=entry_fee,
                            order_id=str(order_id) if order_id else None,
                            position_id=position_id,
                            user_id=self.user_id,
                            notes=verification_notes
                        )

                        # Open position in database
                        self.trade_ledger.open_position(
                            position_id=position_id,
                            symbol=symbol,
                            side=side.upper(),
                            entry_price=final_entry_price,
                            quantity=filled_volume,
                            size_usd=position_size,
                            stop_loss=stop_loss,
                            take_profit_1=take_profit_levels['tp1'],
                            take_profit_2=take_profit_levels['tp2'],
                            take_profit_3=take_profit_levels['tp3'],
                            entry_fee=entry_fee,
                            user_id=self.user_id
                        )

                        logger.info(f"✅ Trade recorded in ledger (ID: {order_id})")
                    except Exception as e:
                        logger.warning(f"Could not record trade in ledger: {e}")

                # Create position record
                position = {
                    'symbol': symbol,
                    'side': side,
                    'market_regime': _regime,
                    'expectancy_bucket': _expectancy_bucket,
                    'entry_price': final_entry_price,
                    'position_size': position_size,
                    'quantity': filled_volume,
                    'position_id': position_id,
                    'order_id': order_id,  # Store order_id for verification
                    'fill_time': fill_time,  # Store fill_time for verification
                    'executed_cost': executed_cost,  # Store executed_cost for verification
                    'stop_loss': stop_loss,
                    'tp1': take_profit_levels['tp1'],
                    'tp2': take_profit_levels['tp2'],
                    'tp3': take_profit_levels['tp3'],
                    'opened_at': datetime.now(),
                    'status': order_status,  # Use confirmed status from order
                    'tp1_hit': False,
                    'tp2_hit': False,
                    'breakeven_moved': False,
                    'remaining_size': 1.0,  # 100%
                    'peak_profit_pct': 0.0  # Track peak profit for protection
                }

                # 🎯 EXECUTION INTELLIGENCE: Record actual execution for learning
                if actual_fill_price:
                    order_side_normalized = 'buy' if side == 'long' else 'sell'
                    self._record_execution_result(
                        symbol=symbol,
                        expected_price=entry_price,
                        actual_price=actual_fill_price,
                        side=order_side_normalized
                    )

                self.positions[symbol] = position
                logger.info(f"Position opened: {symbol} {side} @ {final_entry_price:.2f}")
                logger.info(f"   Order ID: {order_id}, Status: {order_status}")
                _trace(
                    "fill",
                    "filled",
                    "position_opened",
                    terminal=True,
                    extra={"fill_price": float(final_entry_price), "order_id": str(order_id)},
                )

                return position
            else:
                logger.warning("No broker client configured - simulation mode")
                _trace("broker", "rejected", "no_broker_client_configured", terminal=True)
                return None

        except OrderRejectedError as e:
            # Handle order rejection - check if it's a geographic restriction
            error_msg = str(e)
            self._log_order_failure(symbol, position_size, exc=e)

            # Check if this is a geographic restriction and add to blacklist
            self._handle_geographic_restriction_error(symbol, error_msg)
            if SIGNAL_FUNNEL_AVAILABLE and get_signal_funnel is not None:
                try:
                    get_signal_funnel().record_execution_stage(
                        pair=symbol,
                        side=side,
                        stage="broker",
                        outcome="rejected",
                        reason=error_msg or "order_rejected_error",
                        terminal=True,
                    )
                except Exception:
                    pass

            return None

        except Exception as e:
            logger.error(f"Execution error: {e}")
            if SIGNAL_FUNNEL_AVAILABLE and get_signal_funnel is not None:
                try:
                    get_signal_funnel().record_execution_stage(
                        pair=symbol,
                        side=side,
                        stage="broker",
                        outcome="error",
                        reason=str(e),
                        terminal=True,
                    )
                except Exception:
                    pass
            return None

    def execute_exit(self, symbol: str, exit_price: float,
                    size_pct: float = 1.0, reason: str = "") -> bool:
        """
        Execute exit order (full or partial)

        CONCURRENCY FIXES (Issue #1):
        - FIX #1: Atomic position close lock to prevent double-sells
        - FIX #2: Immediate position state flush after confirmed sell
        - FIX #3: Block concurrent exit when active exit in progress

        Args:
            symbol: Trading symbol
            exit_price: Exit price
            size_pct: Percentage of position to exit (0.0 to 1.0)
            reason: Exit reason for logging

        Returns:
            True if successful, False otherwise
        """
        try:
            # ✅ LAYER 0: RECOVERY CONTROLLER - Check if exits are allowed
            if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
                recovery_controller = get_recovery_controller()
                can_trade, trade_reason = recovery_controller.can_trade("exit")
                
                if not can_trade:
                    logger.error("=" * 80)
                    logger.error("🛡️  RECOVERY CONTROLLER BLOCKED EXIT")
                    logger.error("=" * 80)
                    logger.error(f"   Symbol: {symbol}")
                    logger.error(f"   Exit Reason: {reason}")
                    logger.error(f"   Controller Reason: {trade_reason}")
                    logger.error(f"   State: {recovery_controller.current_state.value}")
                    logger.error("=" * 80)
                    # In EMERGENCY_HALT, even exits are blocked
                    return False

            # Bootstrap gate is enforced strictly INSIDE _get_closing_lock() and
            # _get_exit_lock() via _assert_bootstrap_ready_for_execution_locks(strict=True).
            # Those calls BLOCK until FSM reaches READY/RUNNING — no early return,
            # no bypass.  Do NOT add a non-strict pre-check here: it would allow
            # the execution path to bail out silently before the FSM is ready,
            # which is exactly the unsafe bypass we are eliminating.

            # FIX #1: Check if position is already being closed
            with self._get_closing_lock():
                if symbol in self.closing_positions:
                    logger.warning(f"⚠️ CONCURRENCY PROTECTION: {symbol} already being closed, skipping duplicate exit")
                    return False  # Prevent double-sell

            # FIX #3: Check if there's already an active exit order for this symbol
            with self._get_exit_lock():
                if symbol in self.active_exit_orders:
                    logger.warning(f"⚠️ CONCURRENCY PROTECTION: Active exit order for {symbol}, skipping concurrent exit")
                    return False  # Block concurrent exit

            if symbol not in self.positions:
                logger.warning(f"No position found for {symbol}")
                return False

            position = self.positions[symbol]

            # DUST GATE: Do not attempt to sell positions worth less than $5 USD.
            # Prevents dust from entering the execution engine entirely.
            _position_value_usd = position['position_size'] * position['remaining_size']
            if _position_value_usd < 5:
                logger.info(
                    f"🚫 DUST GATE: Skipping sell for {symbol} "
                    f"(${_position_value_usd:.4f} < $5.00) — DO NOTHING"
                )
                return False

            # Calculate exit size
            exit_size = position['position_size'] * position['remaining_size'] * size_pct

            # Calculate P&L for logging
            entry_price = position.get('entry_price', 0)
            side = position.get('side', 'long')
            if entry_price > 0:
                if side == 'long':
                    gross_pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    gross_pnl_pct = (entry_price - exit_price) / entry_price
                broker_fee_pct = self._get_broker_round_trip_fee()
                net_pnl_pct = gross_pnl_pct - broker_fee_pct
                # exit_size is already in USD (position_size * remaining_size * size_pct)
                fees_usd = exit_size * broker_fee_pct
            else:
                gross_pnl_pct = 0
                net_pnl_pct = 0
                fees_usd = 0

            # Log exit attempt with explicit fees and net P&L
            logger.info(f"Executing exit: {symbol} {size_pct*100:.0f}% @ ${exit_price:.2f} - {reason}")
            if entry_price > 0:
                logger.info(f"   Gross P&L: {gross_pnl_pct*100:+.2f}% | Fees: ${fees_usd:.2f} | NET P&L: {net_pnl_pct*100:+.2f}%")

            # FIX #1: Lock this symbol as being closed before submitting order
            with self._get_closing_lock():
                self.closing_positions.add(symbol)

            # FIX #3: Mark as active exit order
            with self._get_exit_lock():
                self.active_exit_orders.add(symbol)

            try:
                result = None
                # Place exit order via broker
                if self.broker_client:
                    order_side = 'sell' if position['side'] == 'long' else 'buy'

                    # ✅ EXCHANGE ORDER COMPILER: Final authority for exit orders
                    _broker_name = "unknown"
                    if hasattr(self.broker_client, "broker_type"):
                        _broker_name = resolve_broker_label(self.broker_client)

                    _exit_compiled_order = None
                    _pricing_snapshot_cls = PricingSnapshot
                    if EXCHANGE_ORDER_COMPILER_AVAILABLE and _eoc and isinstance(_pricing_snapshot_cls, type):
                        try:
                            # Get cached balance snapshot (no exchange polling)
                            _exit_available, _exit_total, _ = self._get_cached_balance_snapshot()
                            _available_balance = float(
                                _exit_available
                                if _exit_available is not None
                                else (_exit_total or 0.0)
                            )

                            # Build pricing snapshot for exit
                            _exit_pricing = _pricing_snapshot_cls(
                                symbol=symbol,
                                bid=exit_price * 0.999,  # Conservative bid
                                ask=exit_price * 1.001,   # Conservative ask
                                mid=exit_price,
                                available_balance_usd=_available_balance,
                            )

                            # Compile exit order
                            _exit_compiled_order = _eoc.compile(
                                symbol=symbol,
                                side="sell" if order_side == "sell" else "buy",
                                size_usd=exit_size,
                                pricing=_exit_pricing,
                                exchange=_broker_name,
                                min_profit_threshold_usd=0.1,  # Minimal threshold for exits
                            )
                            logger.info("[EOC] Exit order compiled: $%.2f (qty=%.8f)",
                                       _exit_compiled_order.size_usd,
                                       _exit_compiled_order.quantity)
                        except Exception as _eoc_exc:
                            if isinstance(OrderCompileError, type) and isinstance(_eoc_exc, OrderCompileError):
                                logger.error(
                                    "[EOC] ❌ EXIT ORDER COMPILATION FAILED: %s — trade REJECTED",
                                    _eoc_exc,
                                )
                                with self._get_closing_lock():
                                    self.closing_positions.discard(symbol)
                                with self._get_exit_lock():
                                    self.active_exit_orders.discard(symbol)
                                return False
                            logger.warning(
                                "[EOC] Exit compilation warning: %s — using fallback",
                                _eoc_exc,
                            )

                    # Use compiled quantity if available
                    if _exit_compiled_order:
                        _exit_quantity = _exit_compiled_order.quantity
                    else:
                        _exit_quantity = exit_size

                    _exit_t0 = _time.monotonic()
                    _exit_exc: Optional[Exception] = None
                    try:
                        result = self._submit_market_order_via_pipeline(
                            broker_client=self.broker_client,
                            symbol=symbol,
                            side=order_side,
                            size_usd=exit_size,
                            price_hint_usd=exit_price,
                            strategy_name="ExecutionEngineExit",
                        )
                    except Exception as _ex_exc:
                        _exit_exc = _ex_exc
                        result = None
                    self._emit_execution_result(symbol, order_side, result, _exit_t0, _exit_exc)
                    if _exit_exc is not None:
                        raise _exit_exc

                    if result:
                        result = self._confirm_order_fill(symbol, order_side, _exit_quantity, result)

                    if self._normalized_order_status(result) == 'error':
                        error_msg = result.get('error') if isinstance(result, dict) else 'unknown_error'
                        logger.error(f"Exit order failed: {error_msg}")

                        # FIX #1: Unlock on confirmed rejection
                        with self._get_closing_lock():
                            self.closing_positions.discard(symbol)

                        # FIX #3: Remove from active exit orders on failure
                        with self._get_exit_lock():
                            self.active_exit_orders.discard(symbol)

                        return False

                    # Calculate exit fee
                    exit_fee = exit_size * 0.006

                    # Record SELL in trade ledger database
                    if self.trade_ledger and hasattr(self.trade_ledger, "record_sell"):
                        try:
                            _ledger = cast(Any, self.trade_ledger)
                            _result_dict = result if isinstance(result, dict) else {}
                            order_id = _result_dict.get('order_id') or _result_dict.get('id')
                            exit_quantity = position.get('quantity', exit_size / exit_price) * size_pct
                            _position_id = str(position.get('position_id') or '')
                            _order_id = str(order_id) if order_id else ''

                            _ledger.record_sell(
                                symbol=symbol,
                                price=exit_price,
                                quantity=exit_quantity,
                                size_usd=exit_size,
                                fee=exit_fee,
                                order_id=_order_id,
                                position_id=_position_id,
                                user_id=self.user_id,
                                notes=f"Exit: {reason}"
                            )
                        except Exception as e:
                            logger.warning(f"Could not record exit in ledger: {e}")

                # Update position
                position['remaining_size'] *= (1.0 - size_pct)

                # Close position if fully exited
                if position['remaining_size'] < 0.01:  # Less than 1% remaining
                    position['status'] = 'closed'
                    position['closed_at'] = datetime.now()

                    # Close position in database
                    if self.trade_ledger and hasattr(self.trade_ledger, "close_position") and position.get('position_id'):
                        try:
                            _ledger = cast(Any, self.trade_ledger)
                            exit_fee = exit_size * 0.006
                            _ledger.close_position(
                                position_id=position['position_id'],
                                exit_price=exit_price,
                                exit_fee=exit_fee,
                                exit_reason=reason
                            )
                        except Exception as e:
                            logger.warning(f"Could not close position in ledger: {e}")

                    logger.info(f"✅ TRADE COMPLETE: {symbol}")
                    
                    # Calculate and log explicit P&L with fees
                    entry_price = position.get('entry_price', 0)
                    position_size_usd = float(position.get('position_size', 0.0) or 0.0)
                    if entry_price > 0:
                        if side == 'long':
                            gross_profit_pct = (exit_price - entry_price) / entry_price
                        else:
                            gross_profit_pct = (entry_price - exit_price) / entry_price
                        broker_fee_pct = self._get_broker_round_trip_fee()
                        net_profit_pct = gross_profit_pct - broker_fee_pct
                        fees_paid_usd = position_size_usd * broker_fee_pct
                        net_profit_usd = position_size_usd * net_profit_pct

                        # Feed realized outcomes into symbol+regime expectancy monitor.
                        self._record_pair_expectancy(
                            symbol,
                            net_profit_pct,
                            regime=str(position.get('market_regime', '')),
                        )
                        
                        logger.info(f"   📊 P&L Summary:")
                        logger.info(f"      Gross P&L: {gross_profit_pct*100:+.2f}% (${position_size_usd * gross_profit_pct:+.2f})")
                        logger.info(f"      Fees Paid: {broker_fee_pct*100:.2f}% (${fees_paid_usd:.2f})")
                        logger.info(f"      NET P&L:   {net_profit_pct*100:+.2f}% (${net_profit_usd:+.2f})")
                    
                    # Log profit confirmation if profit logger available
                    if self.profit_logger:
                        try:
                            entry_price = position.get('entry_price', 0)
                            entry_time = position.get('opened_at')
                            position_size_usd = position.get('position_size', 0)
                            side = position.get('side', 'long')
                            
                            # Calculate profit
                            if side == 'long':
                                gross_profit_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
                            else:
                                gross_profit_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0
                            
                            # Get broker fee (estimate if not available)
                            broker_fee_pct = self._get_broker_round_trip_fee()
                            net_profit_pct = gross_profit_pct - broker_fee_pct
                            net_profit_usd = position_size_usd * net_profit_pct
                            fees_paid_usd = position_size_usd * broker_fee_pct
                            
                            # Calculate hold time
                            if entry_time and isinstance(entry_time, datetime):
                                hold_time_seconds = (datetime.now() - entry_time).total_seconds()
                            else:
                                hold_time_seconds = 0
                            
                            # Determine exit type
                            if "PROFIT" in reason.upper() or "TP" in reason.upper():
                                exit_type = "PROFIT_CONFIRMED"
                            elif "GIVEBACK" in reason.upper():
                                exit_type = "PROFIT_GIVEBACK"
                            elif "STOP" in reason.upper() or "SL" in reason.upper():
                                exit_type = "STOP_LOSS"
                            else:
                                exit_type = "MANUAL_EXIT"
                            
                            # Log the profit confirmation
                            self.profit_logger.log_profit_confirmation(
                                symbol=symbol,
                                entry_price=entry_price,
                                exit_price=exit_price,
                                position_size_usd=position_size_usd,
                                net_profit_pct=net_profit_pct,
                                net_profit_usd=net_profit_usd,
                                hold_time_seconds=hold_time_seconds,
                                exit_type=exit_type,
                                fees_paid_usd=fees_paid_usd,
                                risk_amount_usd=position.get('risk_amount_usd', 0)
                            )
                        except Exception as log_error:
                            logger.warning(f"Could not log profit confirmation: {log_error}")

                    # ── PERFORMANCE TRACKER — record closed trade with fees & slippage ──
                    if PERFORMANCE_TRACKER_AVAILABLE and _get_perf_tracker is not None:
                        try:
                            _pt = _get_perf_tracker()
                            _pt_entry = position.get('entry_price', 0)
                            _pt_qty = position.get('quantity', 0)
                            _pt_side = position.get('side', 'long')
                            _pt_pos_usd = position.get('position_size', 0)
                            _pt_fee_rate = self._get_broker_round_trip_fee()
                            _pt_fees = _pt_pos_usd * _pt_fee_rate

                            # Compute slippage from actual fill vs. signal exit price
                            _pt_actual_fill = self._extract_fill_price(result, symbol) if result else None
                            if _pt_actual_fill and _pt_actual_fill > 0 and exit_price > 0:
                                if _pt_side == 'long':
                                    # Positive = we received more than expected (good)
                                    _pt_slip = (_pt_actual_fill - exit_price) / exit_price * _pt_pos_usd
                                else:
                                    # Positive = we paid less than expected (good)
                                    _pt_slip = (exit_price - _pt_actual_fill) / exit_price * _pt_pos_usd
                            else:
                                _pt_slip = 0.0

                            _pt.record_trade(
                                symbol=symbol,
                                entry_price=_pt_entry,
                                exit_price=exit_price,
                                quantity=_pt_qty,
                                side=_pt_side,
                                fees_usd=_pt_fees,
                                slippage_usd=_pt_slip,
                            )
                        except Exception as _pt_err:
                            logger.debug("PerformanceTracker record_trade skipped for %s: %s", symbol, _pt_err)

                    # FIX #2: Immediate Position State Flush After Sell
                    # Instantly purge the internal position object - DO NOT wait for exchange refresh
                    logger.info(f"🗑️ FLUSHING POSITION STATE: {symbol}")
                    self.close_position(symbol)

                    # ── ADAPTIVE THRESHOLD CONTROLLER — outcome on FULL close only ──
                    # Must NOT fire on entry, TP1 partial, trailing activation, or any
                    # partial exit.  Uses net P&L (after fees) so fee-eroded trades are
                    # never mis-classified as wins.
                    try:
                        from nija_ai_engine import record_trade_outcome as _rto
                        _rto(net_pnl_pct > 0)
                    except Exception:
                        try:
                            from bot.nija_ai_engine import record_trade_outcome as _rto
                            _rto(net_pnl_pct > 0)
                        except Exception as _atc_err:
                            logger.debug(
                                "AdaptiveThresholdController record skipped for %s: %s",
                                symbol, _atc_err,
                            )

                    # ── WEIGHT TUNER + MAB: record outcome for self-learning ──────
                    # Drives: signal-weight gradient update, bandit arm reward,
                    # LR model training, rollback check, batch optimiser.
                    try:
                        from self_learning_weight_tuner import get_weight_tuner as _gwt
                    except ImportError:
                        try:
                            from bot.self_learning_weight_tuner import get_weight_tuner as _gwt
                        except ImportError:
                            _gwt = None  # type: ignore
                    if _gwt is not None:
                        try:
                            _gwt().record_trade_outcome(
                                symbol=symbol,
                                is_win=net_pnl_pct > 0,
                                pnl_pct=float(net_pnl_pct),
                            )
                        except Exception as _wt_err:
                            logger.debug(
                                "WeightTuner record skipped for %s: %s",
                                symbol, _wt_err,
                            )

                    # FIX #1: Unlock after final settlement (position fully closed)
                    with self._get_closing_lock():
                        self.closing_positions.discard(symbol)

                    # FIX #3: Remove from active exit orders after completion
                    with self._get_exit_lock():
                        self.active_exit_orders.discard(symbol)
                else:
                    logger.info(f"Partial exit: {symbol} ({position['remaining_size']*100:.0f}% remaining)")

                    # Partial exit complete - unlock for potential future exits
                    with self._get_closing_lock():
                        self.closing_positions.discard(symbol)

                    # FIX #3: Remove from active exit orders after partial exit completes
                    with self._get_exit_lock():
                        self.active_exit_orders.discard(symbol)

                return True

            except Exception as order_error:
                # FIX #1: Unlock on confirmed failure
                with self._get_closing_lock():
                    self.closing_positions.discard(symbol)

                # FIX #3: Remove from active exit orders on exception
                with self._get_exit_lock():
                    self.active_exit_orders.discard(symbol)

                raise order_error

        except Exception as e:
            logger.error(f"Exit error: {e}")

            # FIX #1: Ensure unlock even on unexpected exceptions
            with self._get_closing_lock():
                self.closing_positions.discard(symbol)

            # FIX #3: Ensure cleanup even on unexpected exceptions
            with self._get_exit_lock():
                self.active_exit_orders.discard(symbol)

            return False

    def update_stop_loss(self, symbol: str, new_stop: float) -> bool:
        """
        Update stop loss for a position

        Args:
            symbol: Trading symbol
            new_stop: New stop loss price

        Returns:
            True if successful
        """
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        old_stop = position['stop_loss']
        position['stop_loss'] = new_stop

        logger.info(f"Updated stop: {symbol} {old_stop:.2f} -> {new_stop:.2f}")
        return True

    def check_stop_loss_hit(self, symbol: str, current_price: float) -> bool:
        """
        Check if stop loss has been hit

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            True if stop loss hit
        """
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]

        if position['side'] == 'long':
            return current_price <= position['stop_loss']
        else:  # short
            return current_price >= position['stop_loss']

    def check_take_profit_hit(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Check which take profit level (if any) has been hit

        This is ALWAYS ACTIVE - ensures profit-taking 24/7 on all accounts, brokerages, and tiers

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            'tp1', 'tp2', 'tp3', or None
        """
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]
        side = position['side']
        entry_price = position.get('entry_price', 0)

        # Calculate current profit/loss
        if side == 'long':
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        else:
            pnl_pct = (entry_price - current_price) / entry_price if entry_price > 0 else 0

        # Check TP3 first (highest level)
        if not position.get('tp3_hit', False):
            if (side == 'long' and current_price >= position['tp3']) or \
               (side == 'short' and current_price <= position['tp3']):
                position['tp3_hit'] = True
                logger.info(f"🎯 TAKE PROFIT TP3 HIT: {symbol} at ${current_price:.2f} (PnL: {pnl_pct*100:+.1f}%)")
                return 'tp3'

        # Check TP2
        if not position.get('tp2_hit', False):
            if (side == 'long' and current_price >= position['tp2']) or \
               (side == 'short' and current_price <= position['tp2']):
                position['tp2_hit'] = True
                logger.info(f"🎯 TAKE PROFIT TP2 HIT: {symbol} at ${current_price:.2f} (PnL: {pnl_pct*100:+.1f}%)")
                return 'tp2'

        # Check TP1
        if not position.get('tp1_hit', False):
            if (side == 'long' and current_price >= position['tp1']) or \
               (side == 'short' and current_price <= position['tp1']):
                position['tp1_hit'] = True
                logger.info(f"🎯 TAKE PROFIT TP1 HIT: {symbol} at ${current_price:.2f} (PnL: {pnl_pct*100:+.1f}%)")
                return 'tp1'

        return None

    def check_stepped_profit_exits(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        Check if position should execute stepped profit-taking exits

        PROFITABILITY_UPGRADE_V7.3 + FEE-AWARE + BROKER-AWARE (Jan 29, 2026)
        Stepped exits now dynamically adjusted based on broker fees.
        RESTORED (Mar 2026): Kraken/Binance use lower thresholds to capture their fee advantage.

        BROKER-SPECIFIC FEE STRUCTURE:
        - Kraken: 0.36% round-trip (0.16% taker x2 + 0.04% spread)
        - Coinbase: 1.4% round-trip (0.6% taker x2 + 0.2% spread)
        - Binance: 0.28% round-trip (0.1% taker x2 + 0.08% spread)
        - OKX: 0.30% round-trip (0.1% taker x2 + 0.1% spread)

        KRAKEN EXAMPLE (0.36% fees):
        - Exit 10% at 1.0% gross profit → ~0.64% NET profit after fees
        - Exit 15% at 1.5% gross profit → ~1.14% NET profit after fees
        - Exit 25% at 2.5% gross profit → ~2.14% NET profit after fees
        - Exit 50% at 4.0% gross profit → ~3.64% NET profit after fees

        COINBASE EXAMPLE (1.4% fees):
        - Exit 10% at 2.0% gross profit → ~0.6% NET profit after fees
        - Exit 15% at 2.5% gross profit → ~1.1% NET profit after fees
        - Exit 25% at 3.5% gross profit → ~2.1% NET profit after fees
        - Exit 50% at 5.0% gross profit → ~3.6% NET profit after fees

        Low-fee brokers (Kraken, Binance) take profits earlier, compounding more
        frequently while Coinbase trades wait for larger moves to clear fees.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            Dictionary with exit_size and profit_level if exit triggered, None otherwise
        """
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]
        side = position['side']
        entry_price = position['entry_price']

        # PROFITABILITY PROTECTION (Jan 27, 2026): Minimum hold time enforcement
        # Prevent premature exits that don't allow trade to develop
        # This ensures we give trades time to profit before closing
        MIN_HOLD_TIME_SECONDS = 90  # 90 seconds (1.5 minutes) minimum hold

        if 'opened_at' in position:
            hold_time = (datetime.now() - position['opened_at']).total_seconds()
            if hold_time < MIN_HOLD_TIME_SECONDS:
                logger.debug(
                    f"⏳ Min hold time not met: {symbol} held for {hold_time:.0f}s "
                    f"(min: {MIN_HOLD_TIME_SECONDS}s)"
                )
                return None  # Don't exit yet, need more time

        # Calculate GROSS profit percentage (before fees)
        if side == 'long':
            gross_profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price

        # Get broker-specific round-trip fee (CRITICAL FIX: Jan 25, 2026)
        broker_round_trip_fee = self._get_broker_round_trip_fee()

        # Calculate NET profit after fees
        net_profit_pct = gross_profit_pct - broker_round_trip_fee

        # PROFIT PROTECTION (Jan 27, 2026): Track peak profit and protect gains
        # This prevents giving back all profits during temporary reversals
        peak_profit = position.get('peak_profit_pct', 0.0)
        if gross_profit_pct > peak_profit:
            position['peak_profit_pct'] = gross_profit_pct
            peak_profit = gross_profit_pct

        # If we've hit significant profit (>2% gross) but are now giving it back,
        # protect at least 50% of peak profit
        PROFIT_PROTECTION_THRESHOLD = 0.02  # Start protecting after 2% peak profit
        PROFIT_PROTECTION_DRAWDOWN = 0.50   # Protect 50% of peak profit

        if peak_profit > PROFIT_PROTECTION_THRESHOLD:
            min_acceptable_profit = peak_profit * (1.0 - PROFIT_PROTECTION_DRAWDOWN)
            if gross_profit_pct < min_acceptable_profit and gross_profit_pct > broker_round_trip_fee:
                # We're giving back too much profit - exit remaining position
                logger.warning(
                    f"⚠️ PROFIT PROTECTION TRIGGERED: {symbol} | "
                    f"Peak: {peak_profit*100:.1f}% → Current: {gross_profit_pct*100:.1f}% | "
                    f"Giving back {(peak_profit - gross_profit_pct)*100:.1f}% of profit"
                )
                logger.info(f"💰 Exiting remaining position to lock in {gross_profit_pct*100:.1f}% profit")

                exit_size = position['position_size'] * position['remaining_size']
                position['remaining_size'] = 0.0

                return {
                    'exit_size': exit_size,
                    'profit_level': 'profit_protection',
                    'exit_pct': 1.0,
                    'gross_profit_pct': gross_profit_pct,
                    'net_profit_pct': net_profit_pct,
                    'current_price': current_price,
                    'entry_price': entry_price,
                    'reason': f'Protecting profit (peak: {peak_profit*100:.1f}%, current: {gross_profit_pct*100:.1f}%)'
                }

        # Enhanced logging for profit-taking visibility (Jan 26, 2026)
        logger.debug(
            f"💹 Profit check: {symbol} | Entry: ${entry_price:.4f} | Current: ${current_price:.4f} | "
            f"Gross P&L: {gross_profit_pct*100:+.2f}% | Net P&L: {net_profit_pct*100:+.2f}% | "
            f"Peak: {peak_profit*100:.1f}% | Remaining: {position.get('remaining_size', 1.0)*100:.0f}%"
        )

        # FEE-AWARE profit thresholds (GROSS profit needed for NET profitability)
        # Dynamically calculated based on broker fees
        # Each threshold ensures NET profit after broker-specific round-trip fees
        #
        # BROKER DIFFERENTIATION (restored Mar 2026):
        # Low-fee brokers (Kraken 0.36%, Binance 0.28%) use LOWER thresholds to
        # capture profits earlier, capitalising on their fee advantage.
        # High-fee brokers (Coinbase 1.4%) require wider thresholds.
        #
        # Risk/reward note: these are PARTIAL exits.  The remaining position runs
        # with a trailing stop, so the first partial peel does not determine the
        # overall trade R/R.

        # Low-fee brokers (Kraken 0.36%, Binance 0.28%, OKX 0.30%)
        # Earlier exits than Coinbase — fee structure makes them profitable sooner.
        # The 0.5% gate covers all current low-fee brokers (max 0.36%) with room
        # for future low-fee brokers up to 0.50%.  Coinbase (1.4%) stays above.
        #
        # PROFIT-OPTIMIZED (Mar 2026): Increased early exit sizes for faster capital
        # recycling and compounding.  Research shows 20-25% early exits (vs the
        # previous 10-15%) capture more profit sooner, freeing capital to re-enter
        # new setups and compound gains faster without sacrificing R/R on the runner.
        if broker_round_trip_fee <= 0.005:  # <= 0.5% fees (Kraken 0.36%, Binance 0.28%, OKX 0.30%)
            exit_levels = [
                (0.010, 0.20, 'tp_exit_1.0pct'),   # Exit 20% at 1.0% gross → ~0.64% NET (up from 10%)
                (0.015, 0.25, 'tp_exit_1.5pct'),   # Exit 25% at 1.5% gross → ~1.14% NET (up from 15%)
                (0.025, 0.30, 'tp_exit_2.5pct'),   # Exit 30% at 2.5% gross → ~2.14% NET (up from 25%)
                (0.040, 0.35, 'tp_exit_4.0pct'),   # Exit 35% at 4.0% gross → ~3.64% NET (runner reduced, more captured early)
            ]
        # High-fee brokers (Coinbase 1.4%)
        else:
            exit_levels = [
                (0.020, 0.20, 'tp_exit_2.0pct'),   # Exit 20% at 2.0% gross → ~0.6% NET (up from 10%)
                (0.025, 0.25, 'tp_exit_2.5pct'),   # Exit 25% at 2.5% gross → ~1.1% NET (up from 15%)
                (0.035, 0.30, 'tp_exit_3.5pct'),   # Exit 30% at 3.5% gross → ~2.1% NET (up from 25%)
                (0.050, 0.35, 'tp_exit_5.0pct'),   # Exit 35% at 5.0% gross → ~3.6% NET (runner reduced, more captured early)
            ]

        for gross_threshold, exit_pct, exit_flag in exit_levels:
            # Skip if already executed
            if position.get(exit_flag, False):
                continue

            # Check if GROSS profit target hit (net will be profitable)
            if gross_profit_pct >= gross_threshold:
                # Mark as executed
                position[exit_flag] = True

                # Calculate exit size
                exit_size = position['position_size'] * position['remaining_size'] * exit_pct

                # Calculate expected NET profit for this exit
                expected_net_pct = gross_threshold - broker_round_trip_fee

                logger.info(f"💰 STEPPED PROFIT EXIT TRIGGERED: {symbol}")
                logger.info(f"   Gross profit: {gross_profit_pct*100:.1f}% | Net profit: {net_profit_pct*100:.1f}%")
                logger.info(f"   Exit level: {exit_flag} | Exit size: {exit_pct*100:.0f}% of position")
                logger.info(f"   Current price: ${current_price:.2f} | Entry: ${entry_price:.2f}")
                logger.info(f"   Broker fees: {broker_round_trip_fee*100:.1f}%")
                logger.info(f"   NET profit: ~{expected_net_pct*100:.1f}% (meets profit criteria)")
                logger.info(f"   Exiting: {exit_pct*100:.0f}% of position (${exit_size:.2f})")
                logger.info(f"   Remaining: {(position['remaining_size'] * (1.0 - exit_pct))*100:.0f}% for trailing stop")

                # Update position
                position['remaining_size'] *= (1.0 - exit_pct)

                return {
                    'exit_size': exit_size,
                    'profit_level': f"{gross_threshold*100:.1f}%",
                    'exit_pct': exit_pct,
                    'gross_profit_pct': gross_profit_pct,
                    'net_profit_pct': expected_net_pct,
                    'current_price': current_price,
                    'entry_price': entry_price
                }

        # Log when no profit exit is triggered (for visibility)
        next_threshold = None
        for gross_threshold, exit_pct, exit_flag in exit_levels:
            if not position.get(exit_flag, False):
                next_threshold = gross_threshold
                break

        if next_threshold:
            progress_pct = (gross_profit_pct / next_threshold * 100) if next_threshold > 0 else 0
            logger.debug(f"   ⏳ Next profit target: {next_threshold*100:.1f}% (currently {progress_pct:.0f}% of the way)")

        return None

    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get open position for symbol. Returns None if position doesn't exist or is closed."""
        position = self.positions.get(symbol)
        # Only return positions that are still open
        if position and position.get('status') == 'open':
            return position
        return None

    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all open positions"""
        return {k: v for k, v in self.positions.items() if v['status'] == 'open'}

    def log_position_profit_status(self, current_prices: Optional[Dict[str, float]] = None):
        """
        Log summary of all positions and their profit status

        Args:
            current_prices: Optional dict of symbol -> current_price
        """
        open_positions = self.get_all_positions()

        if not open_positions:
            logger.info("📊 No open positions - no profit-taking to monitor")
            return

        logger.info("=" * 80)
        logger.info(f"📊 POSITION PROFIT STATUS SUMMARY ({len(open_positions)} open)")
        logger.info("=" * 80)

        broker_round_trip_fee = self._get_broker_round_trip_fee()

        for symbol, position in open_positions.items():
            entry_price = position.get('entry_price', 0)
            remaining_size = position.get('remaining_size', 1.0)
            position_size = position.get('position_size', 0)
            side = position.get('side', 'long')

            # Get current price
            if current_prices and symbol in current_prices:
                current_price = current_prices[symbol]
            else:
                current_price = entry_price  # Fallback

            # Calculate P&L
            if entry_price > 0:
                if side == 'long':
                    gross_pnl = (current_price - entry_price) / entry_price
                else:
                    gross_pnl = (entry_price - current_price) / entry_price
                net_pnl = gross_pnl - broker_round_trip_fee
            else:
                gross_pnl = 0
                net_pnl = 0

            # Determine next profit target
            if broker_round_trip_fee <= 0.005:  # Low-fee broker (Kraken, Binance, OKX)
                # PROFITABILITY FIX (Feb 3, 2026): Widened for 2:1 risk/reward
                next_targets = [0.020, 0.025, 0.030, 0.040]  # 2.0%, 2.5%, 3.0%, 4.0% (was 1.2%, 1.7%, 2.2%, 3.0%)
            else:  # High-fee broker (Coinbase)
                next_targets = [0.025, 0.030, 0.040, 0.050]  # 2.5%, 3.0%, 4.0%, 5.0%

            next_target = None
            for target in next_targets:
                if gross_pnl < target:
                    next_target = target
                    break

            # Emoji indicator
            if net_pnl > 0:
                status_emoji = "🟢"
            elif net_pnl < -0.01:  # -1% or worse
                status_emoji = "🔴"
            else:
                status_emoji = "🟡"

            logger.info(
                f"{status_emoji} {symbol:<12} | Entry: ${entry_price:8.4f} | Current: ${current_price:8.4f} | "
                f"P&L: {gross_pnl*100:+6.2f}% (NET: {net_pnl*100:+6.2f}%) | "
                f"Size: ${position_size * remaining_size:7.2f} ({remaining_size*100:.0f}%)"
            )

            if next_target:
                logger.info(f"      ⏳ Next profit target: {next_target*100:.1f}% gross")

        logger.info("=" * 80)

    def close_position(self, symbol: str):
        """Remove position from tracking"""
        if symbol in self.positions:
            del self.positions[symbol]

    def _extract_fill_price(self, order_result: Dict, symbol: str) -> Optional[float]:
        """
        Extract actual fill price from order result.

        Args:
            order_result: Order result from broker
            symbol: Trading symbol

        Returns:
            Actual fill price or None if not available
        """
        try:
            # Try to get fill price from various possible locations
            # Different brokers may return this in different formats

            # Check for average_filled_price in success_response
            if 'success_response' in order_result:
                success_response = order_result['success_response']
                if 'average_filled_price' in success_response:
                    return float(success_response['average_filled_price'])

            # Check for filled_price in order
            if 'order' in order_result:
                order = order_result['order']
                if isinstance(order, dict):
                    if 'filled_price' in order:
                        return float(order['filled_price'])
                    if 'average_filled_price' in order:
                        return float(order['average_filled_price'])

            # Check direct fields in result
            if 'filled_price' in order_result:
                return float(order_result['filled_price'])
            if 'average_filled_price' in order_result:
                return float(order_result['average_filled_price'])

            # Fallback: try to get current market price from broker
            if self.broker_client and hasattr(self.broker_client, 'get_current_price'):
                current_price = self.broker_client.get_current_price(symbol)
                if current_price and current_price > 0:
                    logger.debug(f"Using current market price as fill price estimate: ${current_price:.2f}")
                    return current_price

            return None

        except Exception as e:
            logger.warning(f"Failed to extract fill price: {e}")
            return None

    def _exceeds_threshold(self, slippage_pct: float) -> bool:
        """
        Check if slippage exceeds the acceptable threshold.

        Handles floating point precision issues by using epsilon tolerance.
        Returns True if slippage is negative (unfavorable) and >= threshold.

        Args:
            slippage_pct: Slippage percentage (negative = unfavorable)

        Returns:
            True if exceeds threshold, False otherwise
        """
        # Only check if slippage is negative (unfavorable)
        if slippage_pct >= 0:
            return False

        # Use epsilon to handle floating point precision
        # (e.g., 0.004999999... should be treated as 0.005)
        EPSILON = 1e-10
        abs_slippage = abs(slippage_pct)

        # Check if exceeds threshold (with epsilon tolerance for exact match)
        return (abs_slippage > self.MAX_IMMEDIATE_LOSS_PCT or
                abs(abs_slippage - self.MAX_IMMEDIATE_LOSS_PCT) < EPSILON)

    def _validate_entry_price(self, symbol: str, side: str, expected_price: float,
                            actual_price: float, position_size: float) -> bool:
        """
        Validate entry price to prevent accepting positions with immediate loss.

        CRITICAL FIX: Prevents NIJA from accepting trades that are immediately
        unprofitable due to excessive spread or slippage.

        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            expected_price: Expected entry price (from analysis)
            actual_price: Actual fill price (from order execution)
            position_size: Position size in USD

        Returns:
            True if entry is acceptable, False if rejected (position will be closed)
        """
        try:
            # Calculate slippage/execution difference
            # For LONG: Bad if we paid more than expected (actual > expected)
            # For SHORT: Bad if we sold for less than expected (actual < expected)

            if side == 'long':
                # For long: Negative slippage means we overpaid (BAD)
                # Positive slippage means we got a better price (GOOD)
                slippage_pct = (expected_price - actual_price) / expected_price
            else:
                # For short: Positive slippage means we got more than expected (GOOD)
                # Negative slippage means we sold for less (BAD)
                slippage_pct = (actual_price - expected_price) / expected_price

            # Calculate dollar amount of slippage
            # For position_size in USD, calculate actual dollar loss from slippage
            # position_size * abs(slippage_pct) gives the dollar amount
            slippage_usd = abs(position_size * slippage_pct)

            logger.info(f"   📊 Entry validation: {symbol} {side}")
            logger.info(f"      Expected: ${expected_price:.4f}")
            logger.info(f"      Actual:   ${actual_price:.4f}")
            logger.info(f"      Slippage: {slippage_pct*100:+.3f}% (${slippage_usd:.2f})")

            # Check if slippage exceeds threshold
            if self._exceeds_threshold(slippage_pct):
                # REJECT: Unfavorable slippage exceeds threshold
                logger.error("=" * 70)
                logger.error(f"🚫 TRADE REJECTED - IMMEDIATE LOSS EXCEEDS THRESHOLD")
                logger.error("=" * 70)
                logger.error(f"   Symbol: {symbol}")
                logger.error(f"   Side: {side}")
                logger.error(f"   Expected price: ${expected_price:.4f}")
                logger.error(f"   Actual fill price: ${actual_price:.4f}")
                logger.error(f"   Unfavorable slippage: {abs(slippage_pct)*100:.2f}% (${slippage_usd:.2f})")
                logger.error(f"   Threshold: {self.MAX_IMMEDIATE_LOSS_PCT*100:.2f}%")
                logger.error(f"   Position size: ${position_size:.2f}")
                logger.error("=" * 70)
                logger.error("   ⚠️ This trade fails mathematical profitability criteria!")
                logger.error("   ⚠️ Likely due to excessive spread or poor market conditions")
                logger.error("   ⚠️ Automatically closing position to prevent loss")
                logger.error("=" * 70)

                # Immediately close the position
                self._close_bad_entry(symbol, side, actual_price, slippage_pct, position_size)

                return False

            # ACCEPT: Entry is within acceptable range
            if slippage_pct >= 0:
                logger.info(f"   ✅ Entry accepted: Filled at favorable price (+{slippage_pct*100:.3f}%)")
            else:
                logger.info(f"   ✅ Entry accepted: Slippage within threshold ({abs(slippage_pct)*100:.3f}% < {self.MAX_IMMEDIATE_LOSS_PCT*100:.2f}%)")

            return True

        except Exception as e:
            logger.error(f"Error validating entry price: {e}")
            # On error, accept the trade to avoid blocking legitimate entries
            return True

    def force_exit_position(self, broker_client, symbol: str, quantity: float,
                           reason: str = "Emergency exit", max_retries: int = 1) -> bool:
        """
        FIX 5: FORCED EXIT PATH - Emergency position exit that bypasses ALL filters

        This is the nuclear option for when stop-loss is hit and position MUST be exited.
        It ignores:
        - Rotation mode restrictions
        - Position caps
        - Minimum trade size requirements
        - Fee optimizer delays
        - All other safety checks and filters

        The ONLY goal is to exit the position immediately using a direct market sell.

        Args:
            broker_client: Broker instance to use for the order
            symbol: Trading symbol to exit
            quantity: Quantity to sell (in base currency)
            reason: Reason for forced exit (logged)
            max_retries: Maximum retry attempts (default: 1, don't retry emergency exits)

        Returns:
            True if exit successful, False otherwise
        """
        try:
            logger.warning(f"🚨 FORCED EXIT TRIGGERED: {symbol}")
            logger.warning(f"   Reason: {reason}")
            logger.warning(f"   Quantity: {quantity}")
            logger.warning(f"   🛡️ PROTECTIVE EXIT MODE — Risk Management Override Active")

            # Attempt 1: Direct market sell
            _px_hint = 0.0
            try:
                if hasattr(broker_client, "get_current_price"):
                    _px_hint = float(broker_client.get_current_price(symbol) or 0.0)
            except Exception:
                _px_hint = 0.0

            result = self._submit_market_order_via_pipeline(
                broker_client=broker_client,
                symbol=symbol,
                side='sell',
                size_usd=quantity * _px_hint,
                price_hint_usd=_px_hint if _px_hint > 0 else None,
                strategy_name="ExecutionEngineForcedExit",
            )

            # Check if successful
            if result and self._normalized_order_status(result) not in ['error', 'unfilled', 'skipped', 'rejected']:
                logger.warning(f"   ✅ FORCED EXIT COMPLETE: {symbol} sold at market")
                logger.warning(f"   Order ID: {result.get('order_id', 'N/A')}")
                return True

            # First attempt failed
            error_msg = result.get('error', 'Unknown error') if result else 'No response'
            logger.error(f"   ❌ FORCED EXIT ATTEMPT 1 FAILED: {error_msg}")

            # Retry if allowed
            if max_retries > 0:
                logger.warning(f"   🔄 Retrying forced exit (attempt 2/{max_retries + 1})...")
                import time
                time.sleep(1)  # Brief pause before retry

                result = self._submit_market_order_via_pipeline(
                    broker_client=broker_client,
                    symbol=symbol,
                    side='sell',
                    size_usd=quantity * _px_hint,
                    price_hint_usd=_px_hint if _px_hint > 0 else None,
                    strategy_name="ExecutionEngineForcedExit",
                )

                if result and self._normalized_order_status(result) not in ['error', 'unfilled', 'skipped', 'rejected']:
                    logger.warning(f"   ✅ FORCED EXIT COMPLETE (retry): {symbol} sold at market")
                    logger.warning(f"   Order ID: {result.get('order_id', 'N/A')}")
                    return True
                else:
                    error_msg = result.get('error', 'Unknown error') if result else 'No response'
                    logger.error(f"   ❌ FORCED EXIT RETRY FAILED: {error_msg}")

            # All attempts failed
            logger.error(f"   🛑 FORCED EXIT FAILED AFTER {max_retries + 1} ATTEMPTS")
            logger.error(f"   🛑 MANUAL INTERVENTION REQUIRED FOR {symbol}")
            logger.error(f"   🛑 Position may still be open - check broker manually")

            return False

        except Exception as e:
            logger.error(f"   ❌ FORCED EXIT EXCEPTION: {symbol}")
            logger.error(f"   Exception: {type(e).__name__}: {e}")
            logger.error(f"   🛑 MANUAL INTERVENTION REQUIRED")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return False

    def _close_bad_entry(self, symbol: str, side: str, entry_price: float,
                        loss_pct: float, position_size: float) -> None:
        """
        Immediately close a position that was accepted with excessive immediate loss.

        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            loss_pct: Immediate loss percentage (negative)
            position_size: Position size in USD
        """
        try:
            logger.warning(f"🚨 Immediately closing bad entry: {symbol}")

            # Place immediate exit order
            if self.broker_client:
                exit_side = 'sell' if side == 'long' else 'buy'

                result = self._submit_market_order_via_pipeline(
                    broker_client=self.broker_client,
                    symbol=symbol,
                    side=exit_side,
                    size_usd=position_size,
                    price_hint_usd=entry_price,
                    strategy_name="ExecutionEngineImmediateClose",
                )

                if self._normalized_order_status(result) == 'error':
                    logger.error(f"   ⚠️ Failed to close bad entry: {result.get('error')}")
                    logger.error(f"   ⚠️ Manual intervention may be required for {symbol}")
                else:
                    logger.info(f"   ✅ Bad entry closed immediately: {symbol}")
                    logger.info(f"   ✅ Prevented loss: ~{abs(loss_pct)*100:.2f}% on ${position_size:.2f}")
                    self.immediate_exit_count += 1
            else:
                logger.error(f"   ⚠️ No broker client available to close bad entry")

        except Exception as e:
            logger.error(f"Error closing bad entry: {e}")
            logger.error(f"⚠️ Manual intervention required to close {symbol}")
