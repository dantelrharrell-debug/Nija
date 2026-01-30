"""
NIJA Copy Trade Engine
======================

Core copy-trading functionality that replicates master account trades to user accounts.

This is the heart of NIJA's copy-trading system. When the master account executes a trade,
this engine automatically replicates it to all active user accounts with appropriate position sizing.

Flow:
    1. Receive trade signal from master account
    2. For each active user account:
        a. Calculate scaled position size based on account equity
        b. Place same order (buy/sell) on user's exchange
        c. Confirm order execution and log order_id
        d. Handle errors without blocking other users
"""

import logging
import threading
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger('nija.copy_engine')

# Import required modules
try:
    from bot.trade_signal_emitter import TradeSignal, get_signal_emitter
    from bot.position_sizer import calculate_user_position_size, round_to_exchange_precision
    from bot.multi_account_broker_manager import multi_account_broker_manager
    from bot.broker_manager import BrokerType, BaseBroker
except ImportError:
    from trade_signal_emitter import TradeSignal, get_signal_emitter
    from position_sizer import calculate_user_position_size, round_to_exchange_precision
    from multi_account_broker_manager import multi_account_broker_manager
    from broker_manager import BrokerType, BaseBroker

# ✅ FIX: Import Kraken adapter for symbol normalization
try:
    from bot.kraken_adapter import normalize_symbol, is_dust_position, DUST_THRESHOLD_USD
except ImportError:
    try:
        from kraken_adapter import normalize_symbol, is_dust_position, DUST_THRESHOLD_USD
    except ImportError:
        # Fallback: no normalization
        normalize_symbol = None
        is_dust_position = None
        DUST_THRESHOLD_USD = 1.00


@dataclass
class CopyTradeResult:
    """Result of copying a trade to a single user."""
    user_id: str
    success: bool
    order_id: Optional[str]
    error_message: Optional[str]
    size: float
    size_type: str


class CopyTradeEngine:
    """
    Engine that copies master trades to user accounts.

    Runs in a background thread, consuming trade signals and replicating them to users.

    Supports two modes:
    - Normal mode: Executes trades on user accounts
    - Observe mode: Tracks balances, positions, P&L but does NOT execute trades
    """

    def __init__(self, multi_account_manager=None, observe_only=False):
        """
        Initialize the copy trade engine.

        Args:
            multi_account_manager: MultiAccountBrokerManager instance (uses global if None)
            observe_only: If True, track signals but don't execute trades (observe mode)
        """
        self.multi_account_manager = multi_account_manager or multi_account_broker_manager
        self.signal_emitter = get_signal_emitter()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._total_trades_copied = 0
        self._total_copy_failures = 0
        self._total_signals_observed = 0  # Track signals in observe mode
        self._lock = threading.Lock()
        self.observe_only = observe_only

        # P2: Initialize trade ledger for copy trade map visibility
        try:
            from bot.trade_ledger_db import get_trade_ledger_db
            self.trade_ledger = get_trade_ledger_db()
        except ImportError:
            try:
                from trade_ledger_db import get_trade_ledger_db
                self.trade_ledger = get_trade_ledger_db()
            except ImportError:
                logger.warning("⚠️  Trade ledger not available - copy trade visibility will be limited")
                self.trade_ledger = None

        logger.info("=" * 70)
        if observe_only:
            logger.info("🔄 COPY TRADE ENGINE INITIALIZED - OBSERVE MODE")
            logger.info("   ⚠️  OBSERVE ONLY: Will track signals but NOT execute trades")
        else:
            logger.info("🔄 COPY TRADE ENGINE INITIALIZED")
        logger.info("=" * 70)

    @property
    def active(self) -> bool:
        """
        Check if the copy trade engine is currently active/running.

        Returns:
            bool: True if engine is running, False otherwise
        """
        return self._running

    def start(self):
        """Start the copy trade engine in a background thread."""
        if self._running:
            logger.warning("⚠️  Copy trade engine already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="CopyTradeEngine")
        self._thread.start()

        logger.info("=" * 70)
        if self.observe_only:
            logger.info("✅ COPY TRADE ENGINE STARTED - OBSERVE MODE")
            logger.info("   👁️  Observing signals (NO trades will execute)")
        else:
            logger.info("✅ COPY TRADE ENGINE STARTED")
        logger.info("=" * 70)
        logger.info("   Listening for master trade signals...")
        logger.info("=" * 70)

    def stop(self):
        """Stop the copy trade engine."""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

        logger.info("=" * 70)
        logger.info("🛑 COPY TRADE ENGINE STOPPED")
        logger.info("=" * 70)
        if self.observe_only:
            logger.info(f"   Total Signals Observed: {self._total_signals_observed}")
        else:
            logger.info(f"   Total Trades Copied: {self._total_trades_copied}")
            logger.info(f"   Total Failures: {self._total_copy_failures}")
        logger.info("=" * 70)

    def _run_loop(self):
        """Main loop that processes trade signals."""
        mode_str = "observe-only" if self.observe_only else "copy-trading"
        logger.info(f"📡 Copy engine thread started in {mode_str} mode, waiting for signals...")

        while self._running:
            try:
                # Wait for next signal (with timeout to allow checking _running flag)
                signal = self.signal_emitter.get_signal(timeout=1.0)

                if signal is None:
                    # No signal available, continue waiting
                    continue

                # Determine signal type for enhanced logging
                is_exit = signal.side.lower() == 'sell'
                signal_type = "EXIT/PROFIT-TAKING" if is_exit else "ENTRY"

                # Process the signal
                logger.info("=" * 70)
                logger.info(f"🔔 RECEIVED MASTER {signal_type} SIGNAL")
                logger.info("=" * 70)
                logger.info(f"   Symbol: {signal.symbol}")
                logger.info(f"   Side: {signal.side.upper()}")
                logger.info(f"   Size: {signal.size} ({signal.size_type})")
                logger.info(f"   Broker: {signal.broker}")
                if is_exit:
                    logger.info(f"   ✅ PROFIT-TAKING: Master is exiting position")
                    logger.info(f"   📤 Users will exit simultaneously")
                logger.info("=" * 70)

                if self.observe_only:
                    # OBSERVE MODE: Log signal but don't execute
                    with self._lock:
                        self._total_signals_observed += 1

                    logger.info("=" * 70)
                    logger.info("👁️  OBSERVE MODE - Signal Logged (NO TRADE EXECUTED)")
                    logger.info("=" * 70)
                    logger.info(f"   Total Signals Observed: {self._total_signals_observed}")
                    logger.info("   ⚠️  Trading is DISABLED in observe mode")
                    logger.info("=" * 70)
                else:
                    # NORMAL MODE: Copy trade to all users
                    results = self.copy_trade_to_users(signal)

                    # Log results with enhanced details
                    successful = sum(1 for r in results if r.success)
                    failed = len(results) - successful

                    logger.info("=" * 70)
                    logger.info("📊 COPY TRADE EXECUTION SUMMARY")
                    logger.info("=" * 70)
                    logger.info(f"   Symbol: {signal.symbol}")
                    logger.info(f"   Side: {signal.side.upper()}")
                    logger.info(f"   Total User Accounts: {len(results)}")
                    logger.info(f"   ✅ Successfully Copied: {successful}")
                    logger.info(f"   ❌ Failed/Blocked: {failed}")
                    if successful > 0:
                        logger.info("")
                        logger.info("   ✅ USERS WHO RECEIVED THIS TRADE:")
                        for r in results:
                            if r.success:
                                # Note: r.size_type comes from CopyTradeResult, which matches the signal's size_type
                                logger.info(f"      • {r.user_id}: ${r.size:.2f} {r.size_type}")
                    if failed > 0:
                        logger.info("")
                        logger.info("   ⚠️  USERS WHO DID NOT RECEIVE THIS TRADE:")
                        for r in results:
                            if not r.success:
                                logger.info(f"      • {r.user_id}: {r.error_message}")
                    logger.info("=" * 70)

            except Exception as e:
                logger.error(f"❌ Error in copy engine loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(1.0)  # Prevent tight error loop

        logger.info("📡 Copy engine thread exiting...")

    def copy_trade_to_users(self, signal: TradeSignal) -> List[CopyTradeResult]:
        """
        Copy a master trade to all active user accounts.

        Args:
            signal: Trade signal from master account

        Returns:
            List of CopyTradeResult objects, one per user
        """
        results: List[CopyTradeResult] = []

        # Get broker type from signal
        broker_type_map = {
            'coinbase': BrokerType.COINBASE,
            'kraken': BrokerType.KRAKEN,
            'okx': BrokerType.OKX,
            'alpaca': BrokerType.ALPACA,
            'binance': BrokerType.BINANCE,
        }

        broker_type = broker_type_map.get(signal.broker.lower())
        if broker_type is None:
            logger.error(f"❌ Unknown broker type: {signal.broker}")
            return results

        # 🔥 CRITICAL: VALIDATE MASTER REQUIREMENTS (non-negotiable)
        # Copy trading will NOT work unless ALL 4 master requirements are met:
        # 1. MASTER PRO_MODE=true
        # 2. LIVE_TRADING=true
        # 3. MASTER_BROKER=KRAKEN (connected)
        # 4. MASTER_CONNECTED=true
        try:
            from bot.copy_trading_requirements import check_master_requirements
        except ImportError:
            try:
                from copy_trading_requirements import check_master_requirements
            except ImportError as e:
                logger.error(f"Failed to import copy trading requirements module: {e}")
                logger.error("Cannot validate copy trading requirements - blocking all copy trades")
                return results

        master_reqs = check_master_requirements(self.multi_account_manager)
        if not master_reqs.all_met():
            unmet = master_reqs.get_unmet_requirements()
            logger.warning("=" * 70)
            logger.warning("❌ COPY TRADING BLOCKED - MASTER REQUIREMENTS NOT MET")
            logger.warning("=" * 70)
            logger.warning("   Master account does not meet requirements for copy trading")
            logger.warning("   Only MASTER will trade - users will NOT receive copy trades")
            logger.warning("")
            logger.warning("   REQUIREMENTS NOT MET:")
            for req in unmet:
                logger.warning(f"      ❌ {req}")
            logger.warning("")
            logger.warning("   🔧 TO ENABLE COPY TRADING, SET THESE:")
            logger.warning("      PRO_MODE=true")
            logger.warning("      LIVE_TRADING=1")
            logger.warning("      KRAKEN_MASTER_API_KEY=<key>")
            logger.warning("      KRAKEN_MASTER_API_SECRET=<secret>")
            logger.warning("=" * 70)
            return results  # Block copy trading when master requirements not met

        # ✅ FIX 5: Copy Trading Should Be Optional
        # CRITICAL CHECK: Verify master account is still connected before copying
        # When master is offline, copy trading is disabled but users can still:
        # 1. Trade independently using run_user_broker_trading_loop() in independent_broker_trader.py
        # 2. Execute their own strategies without waiting for master signals
        # Copy trading is OPTIONAL, not required for user trading
        master_connected = self.multi_account_manager.is_master_connected(broker_type)
        if not master_connected:
            logger.warning("=" * 70)
            logger.warning(f"⚠️  {signal.broker.upper()} MASTER OFFLINE")
            logger.warning("=" * 70)
            logger.warning(f"   Master account is not connected - cannot copy trades")
            logger.warning(f"   Only MASTER will trade when reconnected")
            logger.warning("")
            logger.warning(f"   ℹ️  Users can still trade independently if configured")
            logger.warning(f"   ℹ️  Copy trading will resume when MASTER reconnects")
            logger.warning("=" * 70)
            return results  # Skip copy trading when master offline (users trade independently)

        # Get all user accounts for this broker
        user_brokers = self.multi_account_manager.user_brokers

        # MASTER-ONLY GUARD: Check if master is trading without any followers
        if not user_brokers:
            logger.warning("=" * 70)
            logger.warning("🔒 MASTER-ONLY MODE ACTIVE")
            logger.warning("=" * 70)
            logger.warning("   ⚠️  NO FOLLOWERS ATTACHED")
            logger.warning("   No user accounts are configured to receive copy trades")
            logger.warning("")
            logger.warning("   📊 CURRENT STATUS:")
            logger.warning(f"      Master Broker: {signal.broker.upper()}")
            logger.warning(f"      Master Signal: {signal.side.upper()} {signal.symbol}")
            logger.warning(f"      Follower Count: 0")
            logger.warning("")
            logger.warning("   ⚡ MASTER-ONLY GUARD:")
            logger.warning("      ✓ Master account will execute trade independently")
            logger.warning("      ✓ No copy trades will be distributed")
            logger.warning("      ✓ Master profits are not shared with followers")
            logger.warning("")
            logger.warning("   💡 TO ACTIVATE COPY TRADING:")
            logger.warning("      1. Add user accounts in config/users/")
            logger.warning("      2. Configure user brokers with API credentials")
            logger.warning("      3. Set COPY_TRADING_MODE=MASTER_FOLLOW for users")
            logger.warning("      4. Ensure users have PRO_MODE=true")
            logger.warning("=" * 70)
            return results

        logger.info("=" * 70)
        logger.info(f"🔄 COPY TRADING: Processing {len(user_brokers)} user account(s)")
        logger.info("=" * 70)

        # Process each user account
        for user_id, user_broker_dict in user_brokers.items():
            # Check if user has this broker type
            if broker_type not in user_broker_dict:
                logger.debug(f"   ⏭️  {user_id}: No {signal.broker} account configured")

                # P2: Record skipped trade in trade map
                if self.trade_ledger:
                    try:
                        self.trade_ledger.record_copy_trade(
                            master_trade_id=signal.master_trade_id or signal.order_id,
                            master_symbol=signal.symbol,
                            master_side=signal.side,
                            master_order_id=signal.order_id,
                            user_id=user_id,
                            user_status='skipped',
                            user_error=f"No {signal.broker} account configured"
                        )
                    except Exception as ledger_err:
                        logger.debug(f"Could not record skipped trade: {ledger_err}")

                continue

            user_broker = user_broker_dict[broker_type]

            # Check if broker is connected
            if not user_broker.connected:
                logger.warning(f"   ⚠️  {user_id}: {signal.broker} not connected - skipping")

                # P2: Record skipped trade in trade map
                if self.trade_ledger:
                    try:
                        self.trade_ledger.record_copy_trade(
                            master_trade_id=signal.master_trade_id or signal.order_id,
                            master_symbol=signal.symbol,
                            master_side=signal.side,
                            master_order_id=signal.order_id,
                            user_id=user_id,
                            user_status='skipped',
                            user_error=f"{signal.broker} not connected"
                        )
                    except Exception as ledger_err:
                        logger.debug(f"Could not record skipped trade: {ledger_err}")

                results.append(CopyTradeResult(
                    user_id=user_id,
                    success=False,
                    order_id=None,
                    error_message=f"{signal.broker} not connected",
                    size=0,
                    size_type=signal.size_type
                ))
                continue

            # Copy trade to this user
            result = self._copy_to_single_user(
                user_id=user_id,
                user_broker=user_broker,
                signal=signal
            )
            results.append(result)

        return results

    def _copy_to_single_user(
        self,
        user_id: str,
        user_broker: BaseBroker,
        signal: TradeSignal
    ) -> CopyTradeResult:
        """
        Copy a trade to a single user account.

        Args:
            user_id: User identifier
            user_broker: User's broker instance
            signal: Trade signal to copy

        Returns:
            CopyTradeResult with execution details
        """
        try:
            logger.info(f"   🔄 Copying to user: {user_id}")

            # Get user account balance
            balance_data = user_broker.get_account_balance()
            if not balance_data:
                error_msg = "Could not retrieve account balance"
                logger.error(f"      ❌ {error_msg}")
                with self._lock:
                    self._total_copy_failures += 1
                return CopyTradeResult(
                    user_id=user_id,
                    success=False,
                    order_id=None,
                    error_message=error_msg,
                    size=0,
                    size_type=signal.size_type
                )

            user_balance = balance_data.get('trading_balance', 0.0)
            logger.info(f"      User Balance: ${user_balance:.2f}")
            logger.info(f"      Master Balance: ${signal.master_balance:.2f}")

            # 🔥 CRITICAL: VALIDATE USER REQUIREMENTS (non-negotiable)
            # User will NOT receive copy trades unless ALL 5 requirements are met:
            # 1. USER PRO_MODE=true
            # 2. COPY_TRADING=true (COPY_TRADING_MODE=MASTER_FOLLOW)
            # 3. STANDALONE=false
            # 4. TIER >= STARTER ($50 minimum)
            # 5. INITIAL_CAPITAL >= 100 (for non-STARTER tiers)
            try:
                from bot.copy_trading_requirements import check_user_requirements
            except ImportError:
                try:
                    from copy_trading_requirements import check_user_requirements
                except ImportError as e:
                    logger.error(f"Failed to import copy trading requirements module: {e}")
                    logger.error(f"Cannot validate requirements for {user_id} - skipping copy trade")
                    return CopyTradeResult(
                        user_id=user_id,
                        success=False,
                        order_id=None,
                        error_message="Copy trading requirements module not available",
                        size=0,
                        size_type=signal.size_type
                    )

            # Get copy_from_master setting from user config
            # Default to True if not specified
            copy_from_master = True
            if hasattr(user_broker, 'copy_from_master'):
                copy_from_master = user_broker.copy_from_master

            user_reqs = check_user_requirements(
                user_id=user_id,
                user_balance=user_balance,
                user_broker=user_broker,
                copy_from_master=copy_from_master
            )

            if not user_reqs.all_met():
                unmet = user_reqs.get_unmet_requirements()
                error_msg = f"User requirements not met: {', '.join(unmet)}"
                logger.warning("      " + "=" * 50)
                logger.warning(f"      ⚠️  COPY TRADE BLOCKED FOR {user_id.upper()}")
                logger.warning("      " + "=" * 50)
                logger.warning(f"      User: {user_id}")
                logger.warning(f"      Balance: ${user_balance:.2f}")
                logger.warning("")
                logger.warning("      REQUIREMENTS NOT MET:")
                for req in unmet:
                    logger.warning(f"         ❌ {req}")
                logger.warning("")
                logger.warning("      🔧 TO ENABLE COPY TRADING FOR THIS USER:")
                logger.warning("         1. Ensure PRO_MODE=true")
                logger.warning("         2. Ensure COPY_TRADING_MODE=MASTER_FOLLOW")
                logger.warning("         3. Ensure account balance meets tier minimum")
                logger.warning("         4. Check user config: copy_from_master=true")
                logger.warning("      " + "=" * 50)

                # P2: Record blocked trade in trade map
                if self.trade_ledger:
                    try:
                        self.trade_ledger.record_copy_trade(
                            master_trade_id=signal.master_trade_id or signal.order_id,
                            master_symbol=signal.symbol,
                            master_side=signal.side,
                            master_order_id=signal.order_id,
                            user_id=user_id,
                            user_status='blocked',
                            user_error=error_msg
                        )
                    except Exception as ledger_err:
                        logger.debug(f"Could not record blocked trade: {ledger_err}")

                return CopyTradeResult(
                    user_id=user_id,
                    success=False,
                    order_id=None,
                    error_message=error_msg,
                    size=0,
                    size_type=signal.size_type
                )

            # Calculate scaled position size for user
            sizing_result = calculate_user_position_size(
                master_size=signal.size,
                master_balance=signal.master_balance,
                user_balance=user_balance,
                size_type=signal.size_type,
                symbol=signal.symbol
            )

            if not sizing_result['valid']:
                error_msg = sizing_result['reason']
                logger.warning(f"      ⚠️  Position sizing failed: {error_msg}")
                return CopyTradeResult(
                    user_id=user_id,
                    success=False,
                    order_id=None,
                    error_message=error_msg,
                    size=sizing_result['size'],
                    size_type=signal.size_type
                )

            user_size = sizing_result['size']
            scale_factor = sizing_result['scale_factor']

            # Round to exchange precision
            user_size_rounded = round_to_exchange_precision(
                size=user_size,
                symbol=signal.symbol,
                size_type=signal.size_type
            )

            # ✅ FIX: Normalize symbol for broker if needed
            normalized_symbol = signal.symbol
            if normalize_symbol and signal.broker.lower() == 'kraken':
                normalized_symbol = normalize_symbol(signal.symbol, 'kraken')
                if normalized_symbol != signal.symbol:
                    logger.info(f"      Symbol normalized: {signal.symbol} → {normalized_symbol}")

            logger.info(f"      Calculated Size: {user_size_rounded} ({signal.size_type})")
            logger.info(f"      Scale Factor: {scale_factor:.4f} ({scale_factor*100:.2f}%)")

            # ✅ FIX (MANDATORY): Check if position size is dust (< $1.00 USD)
            # Skip copy trade if the calculated size is below dust threshold
            # Note: For base currency (e.g., BTC), broker validation will catch dust positions
            # since we cannot determine USD value without current price here
            if signal.size_type == 'quote':  # USD value
                position_usd_value = user_size_rounded

                if is_dust_position and is_dust_position(position_usd_value):
                    error_msg = f"Position size ${position_usd_value:.4f} below dust threshold ${DUST_THRESHOLD_USD}"
                    logger.warning(f"      ⚠️  Skipping dust position: {error_msg}")
                    return CopyTradeResult(
                        user_id=user_id,
                        success=False,
                        order_id=None,
                        error_message=error_msg,
                        size=user_size_rounded,
                        size_type=signal.size_type
                    )

            # ========================================
            # FOLLOWER-SIDE SAFEGUARDS
            # ========================================
            # These safeguards protect individual followers without affecting master
            # Each follower executes independently with their own validation
            
            # 1. SLIPPAGE PROTECTION: Validate price hasn't moved too much from master entry
            if signal.price and hasattr(user_broker, 'get_last_price'):
                try:
                    current_price = user_broker.get_last_price(normalized_symbol)
                    if current_price and current_price > 0:
                        price_change_pct = abs((current_price - signal.price) / signal.price) * 100
                        max_slippage_pct = 2.0  # Maximum allowed price movement (configurable)
                        
                        if price_change_pct > max_slippage_pct:
                            error_msg = f"Price moved {price_change_pct:.2f}% (limit: {max_slippage_pct}%), master: ${signal.price:.6f}, current: ${current_price:.6f}"
                            logger.warning(f"      ⚠️  Slippage protection: {error_msg}")
                            logger.warning(f"      Skipping trade to protect follower from excessive slippage")
                            return CopyTradeResult(
                                user_id=user_id,
                                success=False,
                                order_id=None,
                                error_message=error_msg,
                                size=user_size_rounded,
                                size_type=signal.size_type
                            )
                        else:
                            logger.info(f"      ✅ Slippage check passed: {price_change_pct:.2f}% (limit: {max_slippage_pct}%)")
                except Exception as e:
                    logger.debug(f"      Could not validate slippage: {e}")
                    # Fail-safe: Continue with trade (some brokers may not support get_last_price)
            
            # 2. BALANCE SUFFICIENCY: Ensure user has enough free balance for the order
            if signal.side.lower() == 'buy':
                try:
                    free_balance = balance_data.get('available_balance', user_balance)
                    required_balance = user_size_rounded if signal.size_type == 'quote' else user_size_rounded * (current_price if 'current_price' in locals() else signal.price)
                    
                    # Add 1% buffer for fees and price movement
                    required_with_buffer = required_balance * 1.01
                    
                    if free_balance < required_with_buffer:
                        error_msg = f"Insufficient balance: ${free_balance:.2f} available, ${required_with_buffer:.2f} required (includes 1% buffer)"
                        logger.warning(f"      ⚠️  Balance check failed: {error_msg}")
                        return CopyTradeResult(
                            user_id=user_id,
                            success=False,
                            order_id=None,
                            error_message=error_msg,
                            size=user_size_rounded,
                            size_type=signal.size_type
                        )
                    else:
                        logger.info(f"      ✅ Balance check passed: ${free_balance:.2f} available, ${required_with_buffer:.2f} required")
                except Exception as e:
                    logger.debug(f"      Could not validate balance sufficiency: {e}")
                    # Fail-safe: Continue with trade (broker's execute_order will catch insufficient balance)
            
            # 3. MINIMUM ORDER SIZE: Validate against exchange-specific minimums
            # This is additional to the dust threshold check above
            if hasattr(user_broker, 'get_min_order_size'):
                try:
                    min_order_size = user_broker.get_min_order_size(normalized_symbol, signal.size_type)
                    if min_order_size and user_size_rounded < min_order_size:
                        error_msg = f"Order size {user_size_rounded} below exchange minimum {min_order_size} ({signal.size_type})"
                        logger.warning(f"      ⚠️  Min order size check failed: {error_msg}")
                        return CopyTradeResult(
                            user_id=user_id,
                            success=False,
                            order_id=None,
                            error_message=error_msg,
                            size=user_size_rounded,
                            size_type=signal.size_type
                        )
                    elif min_order_size:
                        logger.info(f"      ✅ Min order size check passed: {user_size_rounded} >= {min_order_size}")
                except Exception as e:
                    logger.debug(f"      Could not validate min order size: {e}")
                    # Fail-safe: Continue with trade (broker's execute_order will catch min size violations)
            
            # All follower safeguards passed - proceed with trade execution
            logger.info(f"      📤 Placing {signal.side.upper()} order (follower executes independently)...")

            order_result = user_broker.execute_order(
                symbol=normalized_symbol,  # Use normalized symbol
                side=signal.side,
                quantity=user_size_rounded,
                size_type=signal.size_type
            )

            # Check if order was successful
            # P1: Verify order has FILLED or PARTIALLY_FILLED status
            # This is the second layer of defense after signal emission guard
            order_status = order_result.get('status', 'unknown') if order_result else 'no_response'

            # P1 ENFORCEMENT: Only accept filled orders, not pending/approved signals
            # Consistent with emit_trade_signal() guard which only allows FILLED/PARTIALLY_FILLED
            if order_result and order_status in ['filled', 'FILLED', 'partially_filled', 'PARTIALLY_FILLED']:
                order_id = order_result.get('order_id', order_result.get('id', 'unknown'))
                broker_name = signal.broker.upper()

                logger.info("      " + "=" * 50)
                logger.info("      🟢 COPY TRADE SUCCESS")
                logger.info("      " + "=" * 50)
                logger.info(f"      User: {user_id}")
                # ✅ REQUIREMENT #3: Updated logging for users - "Trade executed in your [broker] account"
                logger.info(f"      ✅ Trade executed in your {broker_name} account")
                logger.info(f"      Order ID: {order_id}")
                logger.info(f"      Symbol: {signal.symbol}")
                logger.info(f"      Side: {signal.side.upper()}")
                logger.info(f"      Size: {user_size_rounded} ({signal.size_type})")
                logger.info(f"      Order Status: {order_status}")
                logger.info("      " + "=" * 50)

                with self._lock:
                    self._total_trades_copied += 1

                # P2: Record copy trade result in trade map for visibility
                if self.trade_ledger:
                    try:
                        self.trade_ledger.record_copy_trade(
                            master_trade_id=signal.master_trade_id or signal.order_id,
                            master_symbol=signal.symbol,
                            master_side=signal.side,
                            master_order_id=signal.order_id,
                            user_id=user_id,
                            user_status='filled',
                            user_order_id=order_id,
                            user_size=user_size_rounded
                        )
                    except Exception as ledger_err:
                        logger.warning(f"      ⚠️  Could not record copy trade in map: {ledger_err}")

                return CopyTradeResult(
                    user_id=user_id,
                    success=True,
                    order_id=order_id,
                    error_message=None,
                    size=user_size_rounded,
                    size_type=signal.size_type
                )
            else:
                # Order failed, unfilled, or has invalid status
                error_msg = order_result.get('error', order_result.get('message', f'Order status: {order_status}')) if order_result else 'No response'
                logger.error("      " + "=" * 50)
                logger.error("      ❌ COPY TRADE FAILED")
                logger.error("      " + "=" * 50)
                logger.error(f"      User: {user_id}")
                logger.error(f"      Error: {error_msg}")
                logger.error(f"      Order Status: {order_status}")
                logger.error("      " + "=" * 50)

                with self._lock:
                    self._total_copy_failures += 1

                # P2: Record copy trade failure in trade map
                if self.trade_ledger:
                    try:
                        self.trade_ledger.record_copy_trade(
                            master_trade_id=signal.master_trade_id or signal.order_id,
                            master_symbol=signal.symbol,
                            master_side=signal.side,
                            master_order_id=signal.order_id,
                            user_id=user_id,
                            user_status='failed',
                            user_error=error_msg,
                            user_size=user_size_rounded
                        )
                    except Exception as ledger_err:
                        logger.warning(f"      ⚠️  Could not record copy trade in map: {ledger_err}")

                return CopyTradeResult(
                    user_id=user_id,
                    success=False,
                    order_id=None,
                    error_message=error_msg,
                    size=user_size_rounded,
                    size_type=signal.size_type
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"      ❌ Exception copying to {user_id}: {error_msg}")
            import traceback
            logger.error(traceback.format_exc())

            with self._lock:
                self._total_copy_failures += 1

            return CopyTradeResult(
                user_id=user_id,
                success=False,
                order_id=None,
                error_message=error_msg,
                size=0,
                size_type=signal.size_type
            )

    def get_stats(self) -> Dict:
        """Get statistics about copy trading."""
        with self._lock:
            stats = {
                'running': self._running,
                'observe_only': self.observe_only,
                'signal_queue_stats': self.signal_emitter.get_stats()
            }

            if self.observe_only:
                stats['total_signals_observed'] = self._total_signals_observed
            else:
                stats['total_trades_copied'] = self._total_trades_copied
                stats['total_failures'] = self._total_copy_failures

            return stats


# Global singleton instance
_copy_engine: Optional[CopyTradeEngine] = None


def get_copy_engine(observe_only: bool = False) -> CopyTradeEngine:
    """
    Get the global copy trade engine instance (singleton pattern).

    Args:
        observe_only: If True, engine runs in observe mode (no trades executed)

    Returns:
        Global CopyTradeEngine instance
    """
    global _copy_engine
    if _copy_engine is None:
        _copy_engine = CopyTradeEngine(observe_only=observe_only)
    return _copy_engine


def start_copy_engine(observe_only: bool = False):
    """
    Start the global copy trade engine.

    Args:
        observe_only: If True, engine runs in observe mode (no trades executed)
    """
    engine = get_copy_engine(observe_only=observe_only)
    engine.start()


def stop_copy_engine():
    """Stop the global copy trade engine."""
    engine = get_copy_engine()
    engine.stop()
