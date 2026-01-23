# execution_engine.py
"""
NIJA Execution Engine
Handles order execution and position management for Apex Strategy v7.1
"""

from typing import Dict, Optional, List
from datetime import datetime
import logging
import sys
import os

logger = logging.getLogger("nija")

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
            
            # Place market order via broker client
            if self.broker_client:
                order_side = 'buy' if side == 'long' else 'sell'
                result = self.broker_client.place_market_order(
                    symbol=symbol,
                    side=order_side,
                    quantity=position_size
                )
                
                # ✅ SAFETY CHECK #2: Hard-stop on rejected orders
                # DO NOT record trade if order failed or was rejected
                if result.get('status') == 'error':
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"❌ Order rejected: {error_msg}")
                    logger.error("   ⚠️  DO NOT RECORD TRADE - Order did not execute")
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
                
                # Log master trade verification data
                logger.info(LOG_SEPARATOR)
                logger.info("✅ MASTER TRADE VERIFICATION")
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
                    'remaining_size': 1.0  # 100%
                }
                
                self.positions[symbol] = position
                logger.info(f"Position opened: {symbol} {side} @ {final_entry_price:.2f}")
                logger.info(f"   Order ID: {order_id}, Status: {order_status}")
                
                return position
            else:
                logger.warning("No broker client configured - simulation mode")
                return None
                
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return None
    
    def execute_exit(self, symbol: str, exit_price: float, 
                    size_pct: float = 1.0, reason: str = "") -> bool:
        """
        Execute exit order (full or partial)
        
        Args:
            symbol: Trading symbol
            exit_price: Exit price
            size_pct: Percentage of position to exit (0.0 to 1.0)
            reason: Exit reason for logging
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if symbol not in self.positions:
                logger.warning(f"No position found for {symbol}")
                return False
            
            position = self.positions[symbol]
            
            # Calculate exit size
            exit_size = position['position_size'] * position['remaining_size'] * size_pct
            
            # Log exit attempt
            logger.info(f"Executing exit: {symbol} {size_pct*100:.0f}% @ {exit_price:.2f} - {reason}")
            
            # Place exit order via broker
            if self.broker_client:
                order_side = 'sell' if position['side'] == 'long' else 'buy'
                result = self.broker_client.place_market_order(
                    symbol=symbol,
                    side=order_side,
                    quantity=exit_size
                )
                
                if result.get('status') == 'error':
                    logger.error(f"Exit order failed: {result.get('error')}")
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
                
                logger.info(f"Position closed: {symbol}")
                
                # Remove closed position from tracking to free slot for new trades
                self.close_position(symbol)
            else:
                logger.info(f"Partial exit: {symbol} ({position['remaining_size']*100:.0f}% remaining)")
            
            return True
            
        except Exception as e:
            logger.error(f"Exit error: {e}")
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
        
        PROFITABILITY_UPGRADE_V7.2 + FEE-AWARE: Stepped exits adjusted for Coinbase fees
        
        Exit Schedule (Fee-Aware Profitability Mode):
        Coinbase round-trip fees: ~1.4% (0.6% entry + 0.6% exit + 0.2% spread)
        
        CRITICAL FEE-AWARE ADJUSTMENT:
        - Exit 10% at 2.0% gross profit → ~0.6% NET profit after fees (PROFITABLE)
        - Exit 15% at 2.5% gross profit → ~1.1% NET profit after fees (PROFITABLE)
        - Exit 25% at 3.0% gross profit → ~1.6% NET profit after fees (PROFITABLE)
        - Exit 50% at 4.0% gross profit → ~2.6% NET profit after fees (PROFITABLE)
        
        OLD BROKEN THRESHOLDS (resulted in losses):
        - 0.5% profit → -0.9% NET (LOSS)
        - 1.0% profit → -0.4% NET (LOSS)
        - 2.0% profit → +0.6% NET (barely profitable)
        
        This dramatically reduces average hold time while ensuring ALL exits are NET PROFITABLE.
        
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
        
        # Calculate GROSS profit percentage (before fees)
        if side == 'long':
            gross_profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price
        
        # Calculate NET profit after fees
        net_profit_pct = gross_profit_pct - DEFAULT_ROUND_TRIP_FEE
        
        # FEE-AWARE profit thresholds (GROSS profit needed for NET profitability)
        # Each threshold ensures NET profit after 1.4% round-trip fees
        exit_levels = [
            (0.020, 0.10, 'tp_exit_2.0pct'),   # Exit 10% at 2.0% gross → ~0.6% NET
            (0.025, 0.15, 'tp_exit_2.5pct'),   # Exit 15% at 2.5% gross → ~1.1% NET
            (0.030, 0.25, 'tp_exit_3.0pct'),   # Exit 25% at 3.0% gross → ~1.6% NET
            (0.040, 0.50, 'tp_exit_4.0pct'),   # Exit 50% at 4.0% gross → ~2.6% NET
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
                expected_net_pct = gross_threshold - DEFAULT_ROUND_TRIP_FEE
                
                logger.info(f"💰 STEPPED PROFIT EXIT TRIGGERED: {symbol}")
                logger.info(f"   Gross profit: {gross_profit_pct*100:.1f}% | Net profit: {net_profit_pct*100:.1f}%")
                logger.info(f"   Exit level: {exit_flag} | Exit size: {exit_pct*100:.0f}% of position")
                logger.info(f"   Current price: ${current_price:.2f} | Entry: ${entry_price:.2f}")
                logger.info(f"   Est. fees: {DEFAULT_ROUND_TRIP_FEE*100:.1f}%")
                logger.info(f"   NET profit: ~{expected_net_pct*100:.1f}% (PROFITABLE)")
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
                logger.error("   ⚠️ This trade would be immediately unprofitable!")
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

