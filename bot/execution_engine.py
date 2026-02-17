# execution_engine.py
"""
NIJA Execution Engine
Handles order execution and position management for Apex Strategy v7.1

Enhanced with Execution Intelligence Layer for optimal trade execution.
"""

from typing import Dict, Optional, List, Set
from datetime import datetime
import logging
import sys
import os
import threading

logger = logging.getLogger("nija")

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

# Constants
VALID_ORDER_STATUSES = ['open', 'closed', 'filled', 'pending']
LOG_SEPARATOR = "=" * 70

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

# Import custom exceptions for safety checks
try:
    from bot.exceptions import (
        ExecutionError, BrokerMismatchError, InvalidTxidError,
        InvalidFillPriceError, OrderRejectedError
    )
except ImportError:
    try:
        from exceptions import (
            ExecutionError, BrokerMismatchError, InvalidTxidError,
            InvalidFillPriceError, OrderRejectedError
        )
    except ImportError:
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

# Import restriction manager for geographic restriction handling
try:
    from bot.restricted_symbols import (
        add_restricted_symbol, is_geographic_restriction_error
    )
    RESTRICTION_MANAGER_AVAILABLE = True
except ImportError:
    try:
        from restricted_symbols import (
            add_restricted_symbol, is_geographic_restriction_error
        )
        RESTRICTION_MANAGER_AVAILABLE = True
    except ImportError:
        RESTRICTION_MANAGER_AVAILABLE = False
        def add_restricted_symbol(symbol, reason=None):
            pass
        def is_geographic_restriction_error(error_msg):
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

        # Initialize trade ledger database
        if TRADE_LEDGER_ENABLED:
            try:
                self.trade_ledger = get_trade_ledger_db()
                logger.info("✅ Trade ledger database connected")
            except Exception as e:
                logger.warning(f"⚠️ Could not connect to trade ledger: {e}")
                self.trade_ledger = None
        else:
            self.trade_ledger = None

        # Initialize Execution Intelligence Layer
        if EXECUTION_INTELLIGENCE_AVAILABLE:
            try:
                self.execution_intelligence = get_execution_intelligence()
                logger.info("✅ Execution Intelligence initialized - Elite optimization enabled")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Execution Intelligence: {e}")
                self.execution_intelligence = None
        else:
            self.execution_intelligence = None
        
        # Initialize Profit Confirmation Logger
        if PROFIT_CONFIRMATION_AVAILABLE and PROFIT_LOGGER_AVAILABLE:
            try:
                self.profit_logger = ProfitConfirmationLogger(data_dir="./data")
                logger.info("✅ Profit Confirmation Logger initialized - Enhanced profit tracking enabled")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize Profit Confirmation Logger: {e}")
                self.profit_logger = None
        else:
            self.profit_logger = None

    def _get_market_microstructure(self, symbol: str) -> Optional[MarketMicrostructure]:
        """
        Get current market microstructure data for execution optimization.

        Args:
            symbol: Trading pair symbol

        Returns:
            MarketMicrostructure object or None if unavailable
        """
        if not EXECUTION_INTELLIGENCE_AVAILABLE or not self.broker_client:
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
    ) -> Optional[ExecutionPlan]:
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

    def execute_entry(self, symbol: str, side: str, position_size: float,
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
            # ✅ CRITICAL SAFETY CHECK #1: LIVE CAPITAL VERIFIED
            # This is the MASTER kill-switch that prevents accidental live trading
            # Check BEFORE any trade execution
            if HARD_CONTROLS_AVAILABLE and get_hard_controls:
                hard_controls = get_hard_controls()
                can_trade, error_msg = hard_controls.can_trade(self.user_id)

                if not can_trade:
                    logger.error("=" * 80)
                    logger.error("🔴 TRADE EXECUTION BLOCKED")
                    logger.error("=" * 80)
                    logger.error(f"   Symbol: {symbol}")
                    logger.error(f"   Side: {side}")
                    logger.error(f"   Position Size: ${position_size:.2f}")
                    logger.error(f"   User ID: {self.user_id}")
                    logger.error(f"   Reason: {error_msg}")
                    logger.error("=" * 80)
                    return None

            # FIX #3 (Jan 19, 2026): Check if broker supports this symbol before attempting trade
            if self.broker_client and hasattr(self.broker_client, 'supports_symbol'):
                if not self.broker_client.supports_symbol(symbol):
                    broker_name = getattr(self.broker_client, 'broker_type', 'unknown')
                    broker_name_str = broker_name.value if hasattr(broker_name, 'value') else str(broker_name)
                    logger.info(f"   ❌ Entry rejected for {symbol}")
                    logger.info(f"      Reason: {broker_name_str.title()} does not support this symbol")
                    logger.info(f"      💡 This symbol may be specific to another exchange (e.g., BUSD is Binance-only)")
                    return None

            # Log entry attempt
            logger.info(f"Executing {side} entry: {symbol} size=${position_size:.2f}")

            # ✅ ENHANCEMENT #1: MINIMUM NOTIONAL GATE
            # Check if entry size meets minimum notional requirements
            if MIN_NOTIONAL_GATE_AVAILABLE and get_minimum_notional_gate:
                notional_gate = get_minimum_notional_gate()
                broker_name = None
                
                # Get broker name if available
                if self.broker_client and hasattr(self.broker_client, 'broker_type'):
                    broker_type = self.broker_client.broker_type
                    if hasattr(broker_type, 'value'):
                        broker_name = broker_type.value
                    else:
                        broker_name = str(broker_type)
                
                # Validate entry size
                is_valid, rejection_reason = notional_gate.validate_entry_size(
                    symbol=symbol,
                    size_usd=position_size,
                    is_stop_loss=False,
                    broker_name=broker_name
                )
                
                if not is_valid:
                    logger.warning(f"❌ Entry rejected: {rejection_reason}")
                    return None

            # 🎯 EXECUTION INTELLIGENCE: Optimize execution before placing order
            execution_plan = self._optimize_execution_with_intelligence(
                symbol=symbol,
                side=side,
                size_usd=position_size,
                urgency=0.7  # Default to moderate urgency for entries
            )

            # Place market order via broker client
            if self.broker_client:
                order_side = 'buy' if side == 'long' else 'sell'

                # Log broker being used for this trade
                broker_name = getattr(self.broker_client, 'broker_type', 'unknown')
                broker_name_str = broker_name.value if hasattr(broker_name, 'value') else str(broker_name)
                logger.info(f"   Using broker: {broker_name_str.upper()}")

                result = self.broker_client.place_market_order(
                    symbol=symbol,
                    side=order_side,
                    quantity=position_size
                )

                # Log the raw result for debugging
                logger.debug(f"   Order result status: {result.get('status', 'N/A')}")

                # ✅ SAFETY CHECK #2: Hard-stop on rejected orders
                # DO NOT record trade if order failed or was rejected
                if result.get('status') == 'error':
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"❌ Order rejected: {error_msg}")
                    logger.error("   ⚠️  DO NOT RECORD TRADE - Order did not execute")

                    # Check if this is a geographic restriction and add to blacklist
                    self._handle_geographic_restriction_error(symbol, error_msg)

                    return None

                # Check for 'unfilled' status which indicates order wasn't placed
                if result.get('status') == 'unfilled':
                    error_msg = result.get('error', result.get('message', 'Order unfilled'))
                    logger.warning(f"⚠️  Order not filled: {error_msg}")
                    logger.warning(f"   Symbol: {symbol}, Size: ${position_size:.2f}")
                    logger.warning("   Possible reasons: insufficient funds, minimum size not met, or other validation failure")
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
                    return None

                # ✅ REQUIREMENT: Confirm status=open or closed
                # BLOCK ledger writes until order status is confirmed
                order_status = result.get('status', '')
                if order_status not in VALID_ORDER_STATUSES:
                    logger.error(LOG_SEPARATOR)
                    logger.error("❌ INVALID ORDER STATUS - CANNOT RECORD POSITION")
                    logger.error(LOG_SEPARATOR)
                    logger.error(f"   Symbol: {symbol}, Side: {side}")
                    logger.error(f"   Order ID: {order_id}")
                    logger.error(f"   Status: {order_status} (expected: {'/'.join(VALID_ORDER_STATUSES)})")
                    logger.error("   ⚠️  Order status must be confirmed before recording position")
                    logger.error(LOG_SEPARATOR)
                    return None

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

                return position
            else:
                logger.warning("No broker client configured - simulation mode")
                return None

        except OrderRejectedError as e:
            # Handle order rejection - check if it's a geographic restriction
            error_msg = str(e)
            logger.error(f"❌ Order rejected: {error_msg}")
            logger.error("   ⚠️  DO NOT RECORD TRADE - Order did not execute")

            # Check if this is a geographic restriction and add to blacklist
            self._handle_geographic_restriction_error(symbol, error_msg)

            return None

        except Exception as e:
            logger.error(f"Execution error: {e}")
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
            # FIX #1: Check if position is already being closed
            with self._closing_lock:
                if symbol in self.closing_positions:
                    logger.warning(f"⚠️ CONCURRENCY PROTECTION: {symbol} already being closed, skipping duplicate exit")
                    return False  # Prevent double-sell

            # FIX #3: Check if there's already an active exit order for this symbol
            with self._exit_lock:
                if symbol in self.active_exit_orders:
                    logger.warning(f"⚠️ CONCURRENCY PROTECTION: Active exit order for {symbol}, skipping concurrent exit")
                    return False  # Block concurrent exit

            if symbol not in self.positions:
                logger.warning(f"No position found for {symbol}")
                return False

            position = self.positions[symbol]

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
            with self._closing_lock:
                self.closing_positions.add(symbol)

            # FIX #3: Mark as active exit order
            with self._exit_lock:
                self.active_exit_orders.add(symbol)

            try:
                # Place exit order via broker
                if self.broker_client:
                    order_side = 'sell' if position['side'] == 'long' else 'buy'
                    result = self.broker_client.place_market_order(
                        symbol=symbol,
                        side=order_side,
                        quantity=exit_size
                    )

                    if result.get('status') == 'error':
                        error_msg = result.get('error')
                        logger.error(f"Exit order failed: {error_msg}")

                        # FIX #1: Unlock on confirmed rejection
                        with self._closing_lock:
                            self.closing_positions.discard(symbol)

                        # FIX #3: Remove from active exit orders on failure
                        with self._exit_lock:
                            self.active_exit_orders.discard(symbol)

                        return False

                    # Calculate exit fee
                    exit_fee = exit_size * 0.006

                    # Record SELL in trade ledger database
                    if self.trade_ledger:
                        try:
                            order_id = result.get('order_id') or result.get('id')
                            exit_quantity = position.get('quantity', exit_size / exit_price) * size_pct

                            self.trade_ledger.record_sell(
                                symbol=symbol,
                                price=exit_price,
                                quantity=exit_quantity,
                                size_usd=exit_size,
                                fee=exit_fee,
                                order_id=str(order_id) if order_id else None,
                                position_id=position.get('position_id'),
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
                    if self.trade_ledger and position.get('position_id'):
                        try:
                            exit_fee = exit_size * 0.006
                            self.trade_ledger.close_position(
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
                    if entry_price > 0:
                        if side == 'long':
                            gross_profit_pct = (exit_price - entry_price) / entry_price
                        else:
                            gross_profit_pct = (entry_price - exit_price) / entry_price
                        broker_fee_pct = self._get_broker_round_trip_fee()
                        net_profit_pct = gross_profit_pct - broker_fee_pct
                        fees_paid_usd = position_size_usd * broker_fee_pct
                        net_profit_usd = position_size_usd * net_profit_pct
                        
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

                    # FIX #2: Immediate Position State Flush After Sell
                    # Instantly purge the internal position object - DO NOT wait for exchange refresh
                    logger.info(f"🗑️ FLUSHING POSITION STATE: {symbol}")
                    self.close_position(symbol)

                    # FIX #1: Unlock after final settlement (position fully closed)
                    with self._closing_lock:
                        self.closing_positions.discard(symbol)

                    # FIX #3: Remove from active exit orders after completion
                    with self._exit_lock:
                        self.active_exit_orders.discard(symbol)
                else:
                    logger.info(f"Partial exit: {symbol} ({position['remaining_size']*100:.0f}% remaining)")

                    # Partial exit complete - unlock for potential future exits
                    with self._closing_lock:
                        self.closing_positions.discard(symbol)

                    # FIX #3: Remove from active exit orders after partial exit completes
                    with self._exit_lock:
                        self.active_exit_orders.discard(symbol)

                return True

            except Exception as order_error:
                # FIX #1: Unlock on confirmed failure
                with self._closing_lock:
                    self.closing_positions.discard(symbol)

                # FIX #3: Remove from active exit orders on exception
                with self._exit_lock:
                    self.active_exit_orders.discard(symbol)

                raise order_error

        except Exception as e:
            logger.error(f"Exit error: {e}")

            # FIX #1: Ensure unlock even on unexpected exceptions
            with self._closing_lock:
                self.closing_positions.discard(symbol)

            # FIX #3: Ensure cleanup even on unexpected exceptions
            with self._exit_lock:
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
        Stepped exits now dynamically adjusted based on broker fees
        OPTIMIZATION: Raised Kraken targets to let winners run longer (0.7%→1.2%, 1.0%→1.7%)

        BROKER-SPECIFIC FEE STRUCTURE:
        - Kraken: 0.36% round-trip (0.16% taker x2 + 0.04% spread)
        - Coinbase: 1.4% round-trip (0.6% taker x2 + 0.2% spread)
        - Binance: 0.28% round-trip (0.1% taker x2 + 0.08% spread)
        - OKX: 0.30% round-trip (0.1% taker x2 + 0.1% spread)

        KRAKEN EXAMPLE (0.36% fees) - OPTIMIZED JAN 29, 2026:
        - Exit 10% at 1.2% gross profit → ~0.84% NET profit after fees (OPTIMIZED from 0.7%)
        - Exit 15% at 1.7% gross profit → ~1.34% NET profit after fees (OPTIMIZED from 1.0%)
        - Exit 25% at 2.2% gross profit → ~1.84% NET profit after fees (OPTIMIZED from 1.5%)
        - Exit 50% at 3.0% gross profit → ~2.64% NET profit after fees (OPTIMIZED from 2.5%)

        COINBASE EXAMPLE (1.4% fees):
        - Exit 10% at 2.0% gross profit → ~0.6% NET profit after fees (meets criteria)
        - Exit 15% at 2.5% gross profit → ~1.1% NET profit after fees (meets criteria)
        - Exit 25% at 3.0% gross profit → ~1.6% NET profit after fees (meets criteria)
        - Exit 50% at 4.0% gross profit → ~2.6% NET profit after fees (meets criteria)

        This ensures faster profit-taking on low-fee brokers (Kraken, Binance, OKX)
        while maintaining profitability on high-fee brokers (Coinbase).

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

        # For low-fee brokers (Kraken 0.36%, Binance 0.28%, OKX 0.30%)
        # PROFITABILITY FIX (Feb 3, 2026): Widened targets for proper risk/reward
        # CRITICAL: With 1.5% stop-loss, need 3.0%+ average targets for 2:1 risk/reward
        # Previous: 1.2%/1.7%/2.2%/3.0% = 2.0% avg (only 1.35:1 risk/reward - below criteria)
        # New: 2.0%/2.5%/3.0%/4.0% = 2.9% avg (1.93:1 risk/reward - meets criteria at 52%+ win rate)
        if broker_round_trip_fee <= 0.005:  # <= 0.5% fees (Kraken, Binance, OKX)
            exit_levels = [
                (0.020, 0.10, 'tp_exit_2.0pct'),   # Exit 10% at 2.0% gross → ~1.64% NET (wider than 1.2%)
                (0.025, 0.15, 'tp_exit_2.5pct'),   # Exit 15% at 2.5% gross → ~2.14% NET (wider than 1.7%)
                (0.030, 0.25, 'tp_exit_3.0pct'),   # Exit 25% at 3.0% gross → ~2.64% NET (wider than 2.2%)
                (0.040, 0.50, 'tp_exit_4.0pct'),   # Exit 50% at 4.0% gross → ~3.64% NET (wider than 3.0%)
            ]
        # For high-fee brokers (Coinbase 1.4%)
        # Use even wider targets due to higher fees
        else:
            exit_levels = [
                (0.025, 0.10, 'tp_exit_2.5pct'),   # Exit 10% at 2.5% gross → ~1.1% NET
                (0.030, 0.15, 'tp_exit_3.0pct'),   # Exit 15% at 3.0% gross → ~1.6% NET
                (0.040, 0.25, 'tp_exit_4.0pct'),   # Exit 25% at 4.0% gross → ~2.6% NET
                (0.050, 0.50, 'tp_exit_5.0pct'),   # Exit 50% at 5.0% gross → ~3.6% NET
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

    def log_position_profit_status(self, current_prices: Dict[str, float] = None):
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
            result = broker_client.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'
            )

            # Check if successful
            if result and result.get('status') not in ['error', 'unfilled']:
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

                result = broker_client.place_market_order(
                    symbol=symbol,
                    side='sell',
                    quantity=quantity,
                    size_type='base'
                )

                if result and result.get('status') not in ['error', 'unfilled']:
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

                result = self.broker_client.place_market_order(
                    symbol=symbol,
                    side=exit_side,
                    quantity=position_size
                )

                if result.get('status') == 'error':
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
