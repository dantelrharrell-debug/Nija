# execution_engine.py
"""
NIJA Execution Engine
Handles order execution and position management for Apex Strategy v7.1
"""

from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger("nija")

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


class ExecutionEngine:
    """
    Manages order execution and position tracking
    Designed to be broker-agnostic and extensible
    """
    
    def __init__(self, broker_client=None):
        """
        Initialize Execution Engine
        
        Args:
            broker_client: Broker client instance (Coinbase, Alpaca, Binance, etc.)
        """
        self.broker_client = broker_client
        self.positions: Dict[str, Dict] = {}
        self.orders: List[Dict] = []
    
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
                
                if result.get('status') == 'error':
                    logger.error(f"Order failed: {result.get('error')}")
                    return None
                
                # Create position record
                position = {
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                    'position_size': position_size,
                    'stop_loss': stop_loss,
                    'tp1': take_profit_levels['tp1'],
                    'tp2': take_profit_levels['tp2'],
                    'tp3': take_profit_levels['tp3'],
                    'opened_at': datetime.now(),
                    'status': 'open',
                    'tp1_hit': False,
                    'tp2_hit': False,
                    'breakeven_moved': False,
                    'remaining_size': 1.0  # 100%
                }
                
                self.positions[symbol] = position
                logger.info(f"Position opened: {symbol} {side} @ {entry_price:.2f}")
                
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
            
            # Update position
            position['remaining_size'] *= (1.0 - size_pct)
            
            # Close position if fully exited
            if position['remaining_size'] < 0.01:  # Less than 1% remaining
                position['status'] = 'closed'
                position['closed_at'] = datetime.now()
                logger.info(f"Position closed: {symbol}")
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
        
        # Check TP3 first (highest level)
        if not position.get('tp3_hit', False):
            if (side == 'long' and current_price >= position['tp3']) or \
               (side == 'short' and current_price <= position['tp3']):
                position['tp3_hit'] = True
                return 'tp3'
        
        # Check TP2
        if not position.get('tp2_hit', False):
            if (side == 'long' and current_price >= position['tp2']) or \
               (side == 'short' and current_price <= position['tp2']):
                position['tp2_hit'] = True
                return 'tp2'
        
        # Check TP1
        if not position.get('tp1_hit', False):
            if (side == 'long' and current_price >= position['tp1']) or \
               (side == 'short' and current_price <= position['tp1']):
                position['tp1_hit'] = True
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
                
                logger.info(f"✅ FEE-AWARE profit exit triggered: {symbol} {side}")
                logger.info(f"  Gross profit: {gross_profit_pct*100:.2f}% ≥ {gross_threshold*100:.1f}% threshold")
                logger.info(f"  Est. fees: {DEFAULT_ROUND_TRIP_FEE*100:.1f}%")
                logger.info(f"  NET profit: ~{expected_net_pct*100:.1f}% (PROFITABLE)")
                logger.info(f"  Exiting: {exit_pct*100:.0f}% of position (${exit_size:.2f})")
                logger.info(f"  Remaining: {(position['remaining_size'] * (1.0 - exit_pct))*100:.0f}% for trailing stop")
                
                # Update position
                position['remaining_size'] *= (1.0 - exit_pct)
                
                return {
                    'exit_size': exit_size,
                    'profit_level': f"{gross_threshold*100:.1f}%",
                    'exit_pct': exit_pct,
                    'gross_profit_pct': gross_profit_pct,
                    'net_profit_pct': expected_net_pct
                }
        
        return None
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get position for symbol"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all open positions"""
        return {k: v for k, v in self.positions.items() if v['status'] == 'open'}
    
    def close_position(self, symbol: str):
        """Remove position from tracking"""
        if symbol in self.positions:
            del self.positions[symbol]
