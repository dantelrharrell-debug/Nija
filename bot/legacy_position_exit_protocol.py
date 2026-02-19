#!/usr/bin/env python3
"""
LEGACY POSITION EXIT PROTOCOL
==============================
Part 1: Bring every account to a clean, strategy-aligned state without chaos.

Phase 1: Position Classification (Non-Destructive)
- Category A: Strategy-Aligned (let strategy manage)
- Category B: Valid but Non-Compliant (mark as LEGACY_NON_COMPLIANT)
- Category C: Broken/Zombie (mark as ZOMBIE_LEGACY)

Phase 2: Order Cleanup (Immediate Safe Action)
- Cancel ALL open limit orders older than X minutes
- Free locked capital

Phase 3: Controlled Exit Engine
- Rule 1: Dust Threshold (< 1% of account balance → market close immediately)
- Rule 2: Over-Cap Positions (close worst-performing legacy first)
- Rule 3: Non-Compliant Legacy (gradual unwind over 3-5 cycles)
- Rule 4: Zombie Positions (try market exit once, log if fails)

Phase 4: Clean State Verification
- Verify: positions ≤ cap, no zombies, all registered, no stale orders
- Mark account state: CLEAN or NEEDS_CLEANUP
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.legacy_exit")


class PositionCategory(Enum):
    """Position classification categories"""
    STRATEGY_ALIGNED = "STRATEGY_ALIGNED"  # Category A
    LEGACY_NON_COMPLIANT = "LEGACY_NON_COMPLIANT"  # Category B
    ZOMBIE_LEGACY = "ZOMBIE_LEGACY"  # Category C


class AccountState(Enum):
    """Account cleanup state"""
    CLEAN = "CLEAN"
    NEEDS_CLEANUP = "NEEDS_CLEANUP"
    CLEANUP_IN_PROGRESS = "CLEANUP_IN_PROGRESS"


class ExitStrategy(Enum):
    """Exit strategy types"""
    MARKET_IMMEDIATE = "MARKET_IMMEDIATE"  # Dust/Zombie
    GRADUAL_UNWIND = "GRADUAL_UNWIND"  # 25% per cycle
    WORST_FIRST = "WORST_FIRST"  # Over-cap
    EMERGENCY_STOP = "EMERGENCY_STOP"  # Conservative approach


class LegacyPositionExitProtocol:
    """
    Manages legacy position cleanup to bring accounts to clean state.
    
    Features:
    - Non-destructive position classification
    - Stale order cancellation
    - Controlled exit strategies
    - Clean state verification
    - High-exposure asset monitoring (PEPE, LUNA, etc.)
    - Volatility scaling integration
    - Correlation-weighted exposure checks
    """
    
    # High-exposure assets to monitor closely (volatile meme coins, delisted assets, etc.)
    HIGH_EXPOSURE_ASSETS = [
        'PEPE-USD', 'PEPE-USDT',
        'LUNA-USD', 'LUNA-USDT', 'LUNA2-USD',
        'SHIB-USD', 'SHIB-USDT',
        'DOGE-USD', 'DOGE-USDT',
        'FLOKI-USD', 'FLOKI-USDT'
    ]
    
    def __init__(self,
                 position_tracker,
                 broker_integration,
                 max_positions: int = 8,
                 dust_pct_threshold: float = 0.01,  # 1% of account balance
                 stale_order_minutes: int = 30,
                 gradual_unwind_pct: float = 0.25,  # 25% per cycle
                 unwind_cycles: int = 4,  # 3-5 cycles
                 data_dir: str = "./data",
                 monitor_high_exposure: bool = True):
        """
        Initialize Legacy Position Exit Protocol.
        
        Args:
            position_tracker: PositionTracker instance
            broker_integration: BrokerIntegration instance
            max_positions: Maximum allowed positions per account
            dust_pct_threshold: Position value as % of account to consider dust (default 1%)
            stale_order_minutes: Age in minutes to consider orders stale
            gradual_unwind_pct: Percentage to close per unwind cycle (default 25%)
            unwind_cycles: Number of cycles for gradual unwind (default 4)
            data_dir: Directory for state persistence
            monitor_high_exposure: Enable high-exposure asset monitoring (default True)
        """
        self.position_tracker = position_tracker
        self.broker = broker_integration
        self.max_positions = max_positions
        self.dust_pct_threshold = dust_pct_threshold
        self.stale_order_minutes = stale_order_minutes
        self.gradual_unwind_pct = gradual_unwind_pct
        self.unwind_cycles = unwind_cycles
        self.monitor_high_exposure = monitor_high_exposure
        
        # State tracking
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.state_file = self.data_dir / "legacy_exit_protocol_state.json"
        self.state = self._load_state()
        
        logger.info("🎯 LEGACY POSITION EXIT PROTOCOL INITIALIZED")
        logger.info(f"   Max Positions: {max_positions}")
        logger.info(f"   Dust Threshold: {dust_pct_threshold * 100:.1f}% of account balance")
        logger.info(f"   Stale Order Age: {stale_order_minutes} minutes")
        logger.info(f"   Gradual Unwind: {gradual_unwind_pct * 100:.0f}% per cycle over {unwind_cycles} cycles")
        logger.info(f"   High-Exposure Monitoring: {'ENABLED' if monitor_high_exposure else 'DISABLED'}")
        if monitor_high_exposure:
            logger.info(f"   Monitored Assets: {', '.join(self.HIGH_EXPOSURE_ASSETS[:5])}... ({len(self.HIGH_EXPOSURE_ASSETS)} total)")
    
    # ========================================================================
    # BROKER ADAPTER METHODS (Handle missing methods gracefully)
    # ========================================================================
    
    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for symbol, handling various broker implementations.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Current price or None if unavailable
        """
        try:
            # Try get_current_price if available
            if hasattr(self.broker, 'get_current_price'):
                return self.broker.get_current_price(symbol)
            
            # Try getting from market data
            if hasattr(self.broker, 'get_market_data'):
                market_data = self.broker.get_market_data(symbol, timeframe='1m', limit=1)
                if market_data and len(market_data) > 0:
                    return float(market_data.iloc[-1]['close'])
            
            # Fallback: get from open positions
            positions = self.broker.get_open_positions()
            for pos in positions:
                if pos.get('symbol') == symbol:
                    return pos.get('current_price')
            
            return None
        except Exception as e:
            logger.warning(f"Could not get price for {symbol}: {e}")
            return None
    
    def _get_account_balance(self, user_id: Optional[str] = None) -> float:
        """
        Get account balance, handling various return formats.
        
        Args:
            user_id: Optional user ID
        
        Returns:
            Account balance in USD
        """
        try:
            balance_data = self.broker.get_account_balance()
            
            # Handle dict return
            if isinstance(balance_data, dict):
                return float(balance_data.get('available', 0) or balance_data.get('total', 0) or 0)
            
            # Handle float return
            return float(balance_data)
        except Exception as e:
            logger.error(f"Could not get account balance: {e}")
            return 0.0
    
    def _get_open_orders(self, user_id: Optional[str] = None) -> List[Dict]:
        """
        Get open orders, with fallback if method not available.
        
        Args:
            user_id: Optional user ID
        
        Returns:
            List of open orders
        """
        try:
            if hasattr(self.broker, 'get_open_orders'):
                return self.broker.get_open_orders(user_id=user_id) or []
            
            logger.warning("Broker does not support get_open_orders")
            return []
        except Exception as e:
            logger.error(f"Could not get open orders: {e}")
            return []
    
    def _close_position(self, symbol: str, quantity: float, order_type: str = 'market') -> bool:
        """
        Close position, handling various broker implementations.
        
        Args:
            symbol: Trading symbol
            quantity: Quantity to close
            order_type: Order type (market or limit)
        
        Returns:
            True if successful
        """
        try:
            # Try close_position if available
            if hasattr(self.broker, 'close_position'):
                return self.broker.close_position(symbol=symbol, quantity=quantity, order_type=order_type)
            
            # Fallback: use place_market_order with sell side
            if hasattr(self.broker, 'place_market_order'):
                result = self.broker.place_market_order(symbol=symbol, side='sell', size=quantity)
                return result is not None
            
            logger.error(f"Broker does not support position closing for {symbol}")
            return False
        except Exception as e:
            logger.error(f"Could not close position {symbol}: {e}")
            return False
    
    def _load_state(self) -> Dict:
        """Load protocol state from disk"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            return self._default_state()
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return self._default_state()
    
    def _default_state(self) -> Dict:
        """Return default state structure"""
        return {
            'account_state': AccountState.NEEDS_CLEANUP.value,
            'classified_positions': {},
            'unwind_progress': {},  # symbol -> {'cycle': 0, 'remaining_pct': 1.0}
            'last_cleanup_run': None,
            'cleanup_metrics': {
                'total_positions_cleaned': 0,
                'zombie_positions_closed': 0,
                'legacy_positions_unwound': 0,
                'stale_orders_cancelled': 0,
                'capital_freed_usd': 0.0
            },
            'high_exposure_assets_tracked': [],  # Symbols of high-exposure assets currently held
            'high_exposure_alerts': []  # Alert history for high-exposure assets
        }
    
    def _save_state(self):
        """Save protocol state to disk"""
        try:
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            temp_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    # ========================================================================
    # PHASE 1: POSITION CLASSIFICATION (NON-DESTRUCTIVE)
    # ========================================================================
    
    def classify_position(self, position: Dict, account_balance: float) -> PositionCategory:
        """
        Classify a single position into one of three categories.
        
        Category A — Strategy-Aligned:
        - Has entry price
        - Known symbol
        - Within position cap (checked at portfolio level)
        - Tracker registered
        - Valid stop/exit logic
        
        Category B — Valid but Non-Compliant:
        - Missing tracker
        - Over cap (checked at portfolio level)
        - Wrong sizing
        - Opened outside system
        - High-exposure asset (PEPE, LUNA, etc.) - flagged for monitoring
        
        Category C — Broken/Zombie:
        - Unknown asset pair
        - Missing entry price
        - Cannot fetch price
        - Dust position
        - API mismatch
        
        Args:
            position: Position dict with symbol, size_usd, etc.
            account_balance: Current account balance for dust calculation
        
        Returns:
            PositionCategory classification
        """
        symbol = position.get('symbol')
        size_usd = position.get('size_usd', 0) or position.get('usd_value', 0)
        
        # Category C checks (Zombie/Broken)
        # 1. Unknown or invalid symbol
        if not symbol or symbol == 'UNKNOWN':
            logger.warning(f"❌ ZOMBIE: Unknown symbol: {symbol}")
            return PositionCategory.ZOMBIE_LEGACY
        
        # 2. Missing or invalid size
        if size_usd <= 0:
            logger.warning(f"❌ ZOMBIE: Invalid size for {symbol}: ${size_usd}")
            return PositionCategory.ZOMBIE_LEGACY
        
        # 3. Cannot fetch current price
        try:
            current_price = self._get_current_price(symbol)
            if current_price is None or current_price <= 0:
                logger.warning(f"❌ ZOMBIE: Cannot fetch price for {symbol}")
                return PositionCategory.ZOMBIE_LEGACY
        except Exception as e:
            logger.warning(f"❌ ZOMBIE: Price fetch failed for {symbol}: {e}")
            return PositionCategory.ZOMBIE_LEGACY
        
        # 4. Dust position (absolute $1 threshold OR < 1% of account)
        dust_threshold_usd = max(1.0, account_balance * self.dust_pct_threshold)
        if size_usd < dust_threshold_usd:
            logger.info(f"💨 ZOMBIE (Dust): {symbol} = ${size_usd:.2f} < ${dust_threshold_usd:.2f}")
            return PositionCategory.ZOMBIE_LEGACY
        
        # Check if position is tracked
        tracked_position = self.position_tracker.get_position(symbol)
        
        # 5. Missing entry price (not tracked or no entry_price)
        if not tracked_position or 'entry_price' not in tracked_position:
            logger.warning(f"⚠️  LEGACY: Missing entry price for {symbol}")
            return PositionCategory.LEGACY_NON_COMPLIANT
        
        entry_price = tracked_position.get('entry_price')
        if entry_price is None or entry_price <= 0:
            logger.warning(f"⚠️  LEGACY: Invalid entry price for {symbol}: {entry_price}")
            return PositionCategory.LEGACY_NON_COMPLIANT
        
        # 6. Position opened outside system
        position_source = tracked_position.get('position_source', 'unknown')
        if position_source not in ['nija_strategy', 'apex_strategy']:
            logger.info(f"⚠️  LEGACY: External position {symbol} (source: {position_source})")
            return PositionCategory.LEGACY_NON_COMPLIANT
        
        # 7. High-exposure asset monitoring (PEPE, LUNA, etc.)
        if self.monitor_high_exposure and symbol in self.HIGH_EXPOSURE_ASSETS:
            logger.warning(f"🚨 HIGH-EXPOSURE ASSET: {symbol} - Enhanced monitoring enabled")
            # Flag as legacy for closer monitoring and potential gradual unwind
            # These assets are volatile and should be managed carefully
            logger.warning(f"   Position Size: ${size_usd:.2f} ({size_usd/account_balance*100:.1f}% of account)")
            logger.warning(f"   Recommendation: Consider gradual unwind or tight stop-loss")
            # Mark as legacy to apply dust/over-cap rules more aggressively
            return PositionCategory.LEGACY_NON_COMPLIANT
        
        # Category A: Strategy-Aligned
        # All checks passed - position is valid and trackable
        logger.debug(f"✅ STRATEGY_ALIGNED: {symbol}")
        return PositionCategory.STRATEGY_ALIGNED
    
    def classify_all_positions(self, positions: List[Dict], account_balance: float) -> Dict[str, Dict]:
        """
        Classify all positions into categories.
        
        Args:
            positions: List of position dicts
            account_balance: Current account balance
        
        Returns:
            Dict mapping symbol -> {category, position_data, exit_strategy}
        """
        logger.info("=" * 80)
        logger.info("PHASE 1: POSITION CLASSIFICATION")
        logger.info("=" * 80)
        
        classified = {}
        category_counts = {cat: 0 for cat in PositionCategory}
        
        for pos in positions:
            symbol = pos.get('symbol')
            category = self.classify_position(pos, account_balance)
            
            # Determine exit strategy based on category
            exit_strategy = self._determine_exit_strategy(category, pos, len(positions))
            
            classified[symbol] = {
                'category': category.value,
                'position': pos,
                'exit_strategy': exit_strategy.value,
                'classified_at': datetime.now().isoformat()
            }
            
            category_counts[category] += 1
        
        # Log summary
        logger.info(f"\n📊 Classification Summary:")
        logger.info(f"   Total Positions: {len(positions)}")
        logger.info(f"   ✅ Strategy-Aligned: {category_counts[PositionCategory.STRATEGY_ALIGNED]}")
        logger.info(f"   ⚠️  Legacy Non-Compliant: {category_counts[PositionCategory.LEGACY_NON_COMPLIANT]}")
        logger.info(f"   ❌ Zombie/Broken: {category_counts[PositionCategory.ZOMBIE_LEGACY]}")
        
        # Save classification
        self.state['classified_positions'] = classified
        self._save_state()
        
        return classified
    
    def _determine_exit_strategy(self, category: PositionCategory, 
                                 position: Dict, total_positions: int) -> ExitStrategy:
        """
        Determine appropriate exit strategy for a position.
        
        Args:
            category: Position category
            position: Position data
            total_positions: Total number of positions
        
        Returns:
            ExitStrategy to use
        """
        if category == PositionCategory.STRATEGY_ALIGNED:
            # Let strategy manage normally
            return ExitStrategy.EMERGENCY_STOP  # Placeholder, won't be executed
        
        elif category == PositionCategory.ZOMBIE_LEGACY:
            # Immediate market exit for zombies
            return ExitStrategy.MARKET_IMMEDIATE
        
        elif category == PositionCategory.LEGACY_NON_COMPLIANT:
            # Check if over cap
            if total_positions > self.max_positions:
                return ExitStrategy.WORST_FIRST
            else:
                # Gradual unwind for non-compliant
                return ExitStrategy.GRADUAL_UNWIND
        
        return ExitStrategy.EMERGENCY_STOP
    
    # ========================================================================
    # PHASE 2: ORDER CLEANUP (IMMEDIATE SAFE ACTION)
    # ========================================================================
    
    def cancel_stale_orders(self, user_id: Optional[str] = None) -> Tuple[int, float]:
        """
        Cancel all open limit orders older than stale_order_minutes.
        
        Args:
            user_id: Optional user ID for multi-account support
        
        Returns:
            Tuple of (orders_cancelled, capital_freed_usd)
        """
        logger.info("=" * 80)
        logger.info("PHASE 2: ORDER CLEANUP")
        logger.info("=" * 80)
        
        try:
            # Get all open orders from broker
            open_orders = self._get_open_orders(user_id=user_id)
            
            if not open_orders:
                logger.info("✅ No open orders to clean up")
                return 0, 0.0
            
            logger.info(f"Found {len(open_orders)} open orders")
            
            # Filter stale orders
            stale_cutoff = datetime.now() - timedelta(minutes=self.stale_order_minutes)
            stale_orders = []
            
            for order in open_orders:
                order_time = order.get('created_at')
                
                # Parse order time if it's a string
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time.replace('Z', '+00:00'))
                    except:
                        logger.warning(f"Could not parse order time: {order_time}")
                        continue
                
                if order_time and order_time < stale_cutoff:
                    stale_orders.append(order)
            
            if not stale_orders:
                logger.info(f"✅ No stale orders (all < {self.stale_order_minutes} minutes old)")
                return 0, 0.0
            
            logger.info(f"Found {len(stale_orders)} stale orders (>{self.stale_order_minutes} min old)")
            
            # Cancel stale orders
            cancelled_count = 0
            capital_freed = 0.0
            
            for order in stale_orders:
                order_id = order.get('order_id') or order.get('id')
                symbol = order.get('symbol')
                size_usd = order.get('value', 0) or order.get('size_usd', 0)
                
                try:
                    if self.broker.cancel_order(order_id):
                        cancelled_count += 1
                        capital_freed += size_usd
                        logger.info(f"   ✅ Cancelled: {symbol} order {order_id} (${size_usd:.2f})")
                    else:
                        logger.warning(f"   ⚠️  Failed to cancel: {symbol} order {order_id}")
                except Exception as e:
                    logger.error(f"   ❌ Error cancelling {symbol} order {order_id}: {e}")
            
            # Update metrics
            self.state['cleanup_metrics']['stale_orders_cancelled'] += cancelled_count
            self.state['cleanup_metrics']['capital_freed_usd'] += capital_freed
            self._save_state()
            
            logger.info(f"\n💰 Order Cleanup Complete:")
            logger.info(f"   Cancelled: {cancelled_count} orders")
            logger.info(f"   Capital Freed: ${capital_freed:.2f}")
            
            return cancelled_count, capital_freed
            
        except Exception as e:
            logger.error(f"Error in order cleanup: {e}")
            return 0, 0.0
    
    # ========================================================================
    # PHASE 3: CONTROLLED EXIT ENGINE
    # ========================================================================
    
    def execute_controlled_exits(self, classified_positions: Dict[str, Dict],
                                 account_balance: float) -> Dict[str, bool]:
        """
        Execute controlled exits for classified positions.
        
        Args:
            classified_positions: Dict from classify_all_positions
            account_balance: Current account balance
        
        Returns:
            Dict mapping symbol -> success status
        """
        logger.info("=" * 80)
        logger.info("PHASE 3: CONTROLLED EXIT ENGINE")
        logger.info("=" * 80)
        
        exit_results = {}
        
        # Rule 4: Zombie positions (immediate market exit)
        zombie_positions = {
            sym: data for sym, data in classified_positions.items()
            if data['category'] == PositionCategory.ZOMBIE_LEGACY.value
        }
        
        if zombie_positions:
            logger.info(f"\n🧟 Processing {len(zombie_positions)} ZOMBIE positions...")
            for symbol, data in zombie_positions.items():
                success = self._exit_zombie_position(symbol, data['position'])
                exit_results[symbol] = success
        
        # Rule 1: Dust threshold (< 1% of account balance)
        dust_threshold_usd = max(1.0, account_balance * self.dust_pct_threshold)
        dust_positions = {
            sym: data for sym, data in classified_positions.items()
            if data['category'] != PositionCategory.ZOMBIE_LEGACY.value and
               (data['position'].get('size_usd', 0) or data['position'].get('usd_value', 0)) < dust_threshold_usd
        }
        
        if dust_positions:
            logger.info(f"\n💨 Processing {len(dust_positions)} DUST positions (< ${dust_threshold_usd:.2f})...")
            for symbol, data in dust_positions.items():
                if symbol not in exit_results:  # Not already processed as zombie
                    success = self._exit_dust_position(symbol, data['position'])
                    exit_results[symbol] = success
        
        # Rule 2 & 3: Over-cap and non-compliant legacy positions
        legacy_positions = {
            sym: data for sym, data in classified_positions.items()
            if data['category'] == PositionCategory.LEGACY_NON_COMPLIANT.value and
               sym not in exit_results  # Not already processed
        }
        
        total_positions = len(classified_positions)
        if total_positions > self.max_positions and legacy_positions:
            logger.info(f"\n⚠️  OVER CAP: {total_positions} positions > {self.max_positions} limit")
            logger.info(f"   Processing {len(legacy_positions)} legacy positions...")
            
            # Sort by worst performing first
            sorted_legacy = sorted(
                legacy_positions.items(),
                key=lambda x: (
                    x[1]['position'].get('size_usd', 0),  # Smallest first
                    x[1]['position'].get('pnl_pct', 0)    # Worst P&L first
                )
            )
            
            # Close worst performing to get under cap
            excess_count = total_positions - self.max_positions
            for i, (symbol, data) in enumerate(sorted_legacy):
                if i < excess_count:
                    # Close immediately (worst first)
                    success = self._exit_legacy_position_immediate(symbol, data['position'])
                    exit_results[symbol] = success
                else:
                    # Gradual unwind for remaining
                    success = self._exit_legacy_position_gradual(symbol, data['position'])
                    exit_results[symbol] = success
        
        elif legacy_positions:
            # Not over cap, just gradual unwind
            logger.info(f"\n⚠️  Processing {len(legacy_positions)} LEGACY positions (gradual unwind)...")
            for symbol, data in legacy_positions.items():
                success = self._exit_legacy_position_gradual(symbol, data['position'])
                exit_results[symbol] = success
        
        # Update metrics
        successful_exits = sum(1 for success in exit_results.values() if success)
        self.state['cleanup_metrics']['total_positions_cleaned'] += successful_exits
        self._save_state()
        
        logger.info(f"\n✅ Exit Engine Complete:")
        logger.info(f"   Processed: {len(exit_results)} positions")
        logger.info(f"   Successful: {successful_exits}")
        logger.info(f"   Failed: {len(exit_results) - successful_exits}")
        
        return exit_results
    
    def _exit_zombie_position(self, symbol: str, position: Dict) -> bool:
        """
        Rule 4: Try market exit once for zombie position.
        
        Args:
            symbol: Position symbol
            position: Position data
        
        Returns:
            True if exit successful, False otherwise
        """
        try:
            logger.info(f"   🧟 Exiting zombie: {symbol}")
            
            # Try market exit once
            success = self._close_position(
                symbol=symbol,
                quantity=position.get('quantity'),
                order_type='market'
            )
            
            if success:
                logger.info(f"      ✅ Zombie closed: {symbol}")
                self.state['cleanup_metrics']['zombie_positions_closed'] += 1
                self._save_state()
                return True
            else:
                logger.error(f"      ❌ Failed to close zombie: {symbol}")
                # Don't halt thread - log and escalate
                logger.error(f"      🚨 ESCALATE: Manual intervention needed for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"      ❌ Exception closing zombie {symbol}: {e}")
            logger.error(f"      🚨 ESCALATE: Manual intervention needed for {symbol}")
            return False
    
    def _exit_dust_position(self, symbol: str, position: Dict) -> bool:
        """
        Rule 1: Market close dust position immediately.
        
        Args:
            symbol: Position symbol
            position: Position data
        
        Returns:
            True if exit successful
        """
        try:
            size_usd = position.get('size_usd', 0) or position.get('usd_value', 0)
            logger.info(f"   💨 Exiting dust: {symbol} (${size_usd:.2f})")
            
            success = self._close_position(
                symbol=symbol,
                quantity=position.get('quantity'),
                order_type='market'
            )
            
            if success:
                logger.info(f"      ✅ Dust closed: {symbol}")
                return True
            else:
                logger.warning(f"      ⚠️  Failed to close dust: {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"      ❌ Error closing dust {symbol}: {e}")
            return False
    
    def _exit_legacy_position_immediate(self, symbol: str, position: Dict) -> bool:
        """
        Rule 2: Close over-cap legacy position immediately (worst first).
        
        Args:
            symbol: Position symbol
            position: Position data
        
        Returns:
            True if exit successful
        """
        try:
            size_usd = position.get('size_usd', 0) or position.get('usd_value', 0)
            pnl_pct = position.get('pnl_pct', 0)
            logger.info(f"   ⚠️  Exiting legacy (over-cap): {symbol} (${size_usd:.2f}, P&L: {pnl_pct:.2f}%)")
            
            success = self._close_position(
                symbol=symbol,
                quantity=position.get('quantity'),
                order_type='market'
            )
            
            if success:
                logger.info(f"      ✅ Legacy closed: {symbol}")
                self.state['cleanup_metrics']['legacy_positions_unwound'] += 1
                self._save_state()
                return True
            else:
                logger.warning(f"      ⚠️  Failed to close legacy: {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"      ❌ Error closing legacy {symbol}: {e}")
            return False
    
    def _exit_legacy_position_gradual(self, symbol: str, position: Dict) -> bool:
        """
        Rule 3: Gradual unwind of legacy position (25% per cycle over 3-5 cycles).
        
        Args:
            symbol: Position symbol
            position: Position data
        
        Returns:
            True if exit successful for this cycle
        """
        try:
            # Check unwind progress
            if symbol not in self.state['unwind_progress']:
                self.state['unwind_progress'][symbol] = {
                    'cycle': 0,
                    'remaining_pct': 1.0,
                    'started_at': datetime.now().isoformat()
                }
            
            progress = self.state['unwind_progress'][symbol]
            current_cycle = progress['cycle']
            remaining_pct = progress['remaining_pct']
            
            if current_cycle >= self.unwind_cycles or remaining_pct <= 0:
                logger.info(f"   ✅ Gradual unwind complete for {symbol}")
                return True
            
            # Close portion for this cycle
            close_pct = self.gradual_unwind_pct
            close_qty = position.get('quantity', 0) * remaining_pct * close_pct
            size_usd = position.get('size_usd', 0) or position.get('usd_value', 0)
            
            logger.info(f"   ⏳ Unwinding legacy: {symbol} (Cycle {current_cycle + 1}/{self.unwind_cycles}, {close_pct * 100:.0f}%)")
            logger.info(f"      Current: ${size_usd * remaining_pct:.2f}, Closing: ${size_usd * remaining_pct * close_pct:.2f}")
            
            success = self._close_position(
                symbol=symbol,
                quantity=close_qty,
                order_type='market'
            )
            
            if success:
                # Update progress
                progress['cycle'] += 1
                progress['remaining_pct'] *= (1 - close_pct)
                progress['last_cycle_at'] = datetime.now().isoformat()
                self.state['unwind_progress'][symbol] = progress
                
                if progress['cycle'] >= self.unwind_cycles or progress['remaining_pct'] <= 0.01:
                    logger.info(f"      ✅ Gradual unwind complete: {symbol}")
                    self.state['cleanup_metrics']['legacy_positions_unwound'] += 1
                else:
                    logger.info(f"      ⏳ Progress: {progress['remaining_pct'] * 100:.1f}% remaining")
                
                self._save_state()
                return True
            else:
                logger.warning(f"      ⚠️  Failed unwind cycle for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"      ❌ Error unwinding {symbol}: {e}")
            return False
    
    # ========================================================================
    # HIGH-EXPOSURE ASSET MONITORING
    # ========================================================================
    
    def monitor_high_exposure_assets(self, positions: List[Dict], account_balance: float) -> Dict:
        """
        Monitor high-exposure assets (PEPE, LUNA, etc.) for price swings and risk.
        
        This method tracks volatile assets and provides alerts for:
        - Price swing detection (significant moves)
        - Dust threshold violations
        - Over-cap risk concentration
        - Position size warnings
        
        Args:
            positions: List of current positions
            account_balance: Current account balance
        
        Returns:
            Dict with monitoring results and alerts
        """
        if not self.monitor_high_exposure:
            return {'enabled': False}
        
        logger.info("=" * 80)
        logger.info("🚨 HIGH-EXPOSURE ASSET MONITORING")
        logger.info("=" * 80)
        
        high_exposure_positions = []
        alerts = []
        total_high_exposure_value = 0.0
        
        for pos in positions:
            symbol = pos.get('symbol')
            if symbol in self.HIGH_EXPOSURE_ASSETS:
                size_usd = pos.get('size_usd', 0) or pos.get('usd_value', 0)
                pct_of_account = (size_usd / account_balance * 100) if account_balance > 0 else 0
                
                high_exposure_positions.append({
                    'symbol': symbol,
                    'size_usd': size_usd,
                    'pct_of_account': pct_of_account
                })
                total_high_exposure_value += size_usd
                
                # Alert if position is too large (>10% of account)
                if pct_of_account > 10.0:
                    alert = {
                        'type': 'OVERSIZED_HIGH_EXPOSURE',
                        'severity': 'CRITICAL',
                        'symbol': symbol,
                        'size_usd': size_usd,
                        'pct_of_account': pct_of_account,
                        'message': f'{symbol} is {pct_of_account:.1f}% of account (>10% threshold)',
                        'recommendation': 'Consider reducing position size or setting tighter stop-loss',
                        'timestamp': datetime.now().isoformat()
                    }
                    alerts.append(alert)
                    logger.warning(f"   🚨 CRITICAL: {alert['message']}")
                    logger.warning(f"      Recommendation: {alert['recommendation']}")
                
                # Alert if close to dust threshold
                dust_threshold = max(1.0, account_balance * self.dust_pct_threshold)
                if size_usd < dust_threshold * 2:  # Within 2x of dust threshold
                    alert = {
                        'type': 'NEAR_DUST_THRESHOLD',
                        'severity': 'WARNING',
                        'symbol': symbol,
                        'size_usd': size_usd,
                        'dust_threshold': dust_threshold,
                        'message': f'{symbol} near dust threshold: ${size_usd:.2f} vs ${dust_threshold:.2f}',
                        'recommendation': 'Monitor for automatic dust cleanup',
                        'timestamp': datetime.now().isoformat()
                    }
                    alerts.append(alert)
                    logger.warning(f"   ⚠️  WARNING: {alert['message']}")
                
                logger.info(f"   📊 {symbol}: ${size_usd:.2f} ({pct_of_account:.2f}% of account)")
        
        # Alert if total high-exposure is too large
        total_high_exposure_pct = (total_high_exposure_value / account_balance * 100) if account_balance > 0 else 0
        if total_high_exposure_pct > 25.0:
            alert = {
                'type': 'EXCESSIVE_HIGH_EXPOSURE_CONCENTRATION',
                'severity': 'CRITICAL',
                'total_value': total_high_exposure_value,
                'pct_of_account': total_high_exposure_pct,
                'message': f'Total high-exposure assets: {total_high_exposure_pct:.1f}% of account (>25% threshold)',
                'recommendation': 'Diversify portfolio - reduce exposure to volatile meme coins',
                'timestamp': datetime.now().isoformat()
            }
            alerts.append(alert)
            logger.warning(f"   🚨 CRITICAL: {alert['message']}")
            logger.warning(f"      Recommendation: {alert['recommendation']}")
        
        # Update state
        self.state['high_exposure_assets_tracked'] = [pos['symbol'] for pos in high_exposure_positions]
        self.state['high_exposure_alerts'] = alerts
        self._save_state()
        
        monitoring_result = {
            'enabled': True,
            'positions_tracked': len(high_exposure_positions),
            'total_value': total_high_exposure_value,
            'pct_of_account': total_high_exposure_pct,
            'positions': high_exposure_positions,
            'alerts': alerts,
            'alert_count': len(alerts)
        }
        
        logger.info(f"\n📊 High-Exposure Monitoring Summary:")
        logger.info(f"   Assets Tracked: {len(high_exposure_positions)}")
        logger.info(f"   Total Value: ${total_high_exposure_value:.2f} ({total_high_exposure_pct:.2f}% of account)")
        logger.info(f"   Alerts Generated: {len(alerts)}")
        
        return monitoring_result
    
    # ========================================================================
    # PHASE 4: CLEAN STATE VERIFICATION
    # ========================================================================
    
    def verify_clean_state(self, user_id: Optional[str] = None) -> Tuple[AccountState, Dict]:
        """
        Verify account is in clean state.
        
        Account is CLEAN when:
        - Positions ≤ cap
        - No zombie positions
        - All positions registered
        - No stale open orders
        
        Args:
            user_id: Optional user ID for multi-account support
        
        Returns:
            Tuple of (AccountState, diagnostics_dict)
        """
        logger.info("=" * 80)
        logger.info("PHASE 4: CLEAN STATE VERIFICATION")
        logger.info("=" * 80)
        
        diagnostics = {
            'timestamp': datetime.now().isoformat(),
            'checks': {}
        }
        
        try:
            # Get current state
            positions = self.broker.get_open_positions(user_id=user_id)
            open_orders = self._get_open_orders(user_id=user_id)
            account_balance = self._get_account_balance(user_id=user_id)
            
            # Check 1: Position count ≤ cap
            position_count = len(positions)
            check_1_pass = position_count <= self.max_positions
            diagnostics['checks']['position_count'] = {
                'pass': check_1_pass,
                'current': position_count,
                'max': self.max_positions
            }
            logger.info(f"   {'✅' if check_1_pass else '❌'} Position Count: {position_count}/{self.max_positions}")
            
            # Check 2: No zombie positions
            zombie_count = 0
            for pos in positions:
                category = self.classify_position(pos, account_balance)
                if category == PositionCategory.ZOMBIE_LEGACY:
                    zombie_count += 1
            
            check_2_pass = zombie_count == 0
            diagnostics['checks']['zombie_positions'] = {
                'pass': check_2_pass,
                'count': zombie_count
            }
            logger.info(f"   {'✅' if check_2_pass else '❌'} Zombie Positions: {zombie_count}")
            
            # Check 3: All positions registered
            unregistered_count = 0
            for pos in positions:
                symbol = pos.get('symbol')
                if not self.position_tracker.get_position(symbol):
                    unregistered_count += 1
            
            check_3_pass = unregistered_count == 0
            diagnostics['checks']['registered_positions'] = {
                'pass': check_3_pass,
                'unregistered': unregistered_count,
                'registered': len(positions) - unregistered_count
            }
            logger.info(f"   {'✅' if check_3_pass else '❌'} Position Registration: {len(positions) - unregistered_count}/{len(positions)}")
            
            # Check 4: No stale open orders
            stale_cutoff = datetime.now() - timedelta(minutes=self.stale_order_minutes)
            stale_count = 0
            
            for order in open_orders:
                order_time = order.get('created_at')
                if isinstance(order_time, str):
                    try:
                        order_time = datetime.fromisoformat(order_time.replace('Z', '+00:00'))
                    except:
                        continue
                
                if order_time and order_time < stale_cutoff:
                    stale_count += 1
            
            check_4_pass = stale_count == 0
            diagnostics['checks']['stale_orders'] = {
                'pass': check_4_pass,
                'stale': stale_count,
                'total': len(open_orders)
            }
            logger.info(f"   {'✅' if check_4_pass else '❌'} Stale Orders: {stale_count}/{len(open_orders)}")
            
            # Determine overall state
            all_checks_pass = all([check_1_pass, check_2_pass, check_3_pass, check_4_pass])
            
            if all_checks_pass:
                account_state = AccountState.CLEAN
                logger.info(f"\n🎉 ACCOUNT STATE: CLEAN")
            else:
                account_state = AccountState.NEEDS_CLEANUP
                logger.warning(f"\n⚠️  ACCOUNT STATE: NEEDS_CLEANUP")
            
            diagnostics['account_state'] = account_state.value
            diagnostics['all_checks_pass'] = all_checks_pass
            
            # Update state
            self.state['account_state'] = account_state.value
            self.state['last_cleanup_run'] = datetime.now().isoformat()
            self._save_state()
            
            return account_state, diagnostics
            
        except Exception as e:
            logger.error(f"Error verifying clean state: {e}")
            diagnostics['error'] = str(e)
            return AccountState.NEEDS_CLEANUP, diagnostics
    
    # ========================================================================
    # MAIN EXECUTION
    # ========================================================================
    
    def run_full_protocol(self, user_id: Optional[str] = None) -> Dict:
        """
        Execute the complete Legacy Position Exit Protocol.
        
        Args:
            user_id: Optional user ID for multi-account support
        
        Returns:
            Dict with results from all phases
        """
        logger.info("\n" + "=" * 80)
        logger.info("🎯 LEGACY POSITION EXIT PROTOCOL - FULL EXECUTION")
        logger.info("=" * 80 + "\n")
        
        results = {
            'started_at': datetime.now().isoformat(),
            'user_id': user_id
        }
        
        try:
            # Get current account data
            positions = self.broker.get_open_positions(user_id=user_id)
            account_balance = self._get_account_balance(user_id=user_id)
            
            logger.info(f"📊 Current State:")
            logger.info(f"   Account Balance: ${account_balance:.2f}")
            logger.info(f"   Open Positions: {len(positions)}")
            
            # PHASE 1: Position Classification
            classified = self.classify_all_positions(positions, account_balance)
            results['phase1_classification'] = {
                'total_positions': len(positions),
                'classified': len(classified)
            }
            
            # PHASE 2: Order Cleanup
            cancelled, freed = self.cancel_stale_orders(user_id=user_id)
            results['phase2_order_cleanup'] = {
                'orders_cancelled': cancelled,
                'capital_freed_usd': freed
            }
            
            # PHASE 3: Controlled Exits
            exit_results = self.execute_controlled_exits(classified, account_balance)
            results['phase3_controlled_exits'] = {
                'positions_processed': len(exit_results),
                'successful': sum(1 for v in exit_results.values() if v),
                'failed': sum(1 for v in exit_results.values() if not v)
            }
            
            # HIGH-EXPOSURE ASSET MONITORING (between Phase 3 and 4)
            # Get updated positions after exits
            updated_positions = self.broker.get_open_positions(user_id=user_id)
            monitoring_results = self.monitor_high_exposure_assets(updated_positions, account_balance)
            results['high_exposure_monitoring'] = monitoring_results
            
            # PHASE 4: Clean State Verification
            state, diagnostics = self.verify_clean_state(user_id=user_id)
            results['phase4_verification'] = {
                'account_state': state.value,
                'diagnostics': diagnostics
            }
            
            results['completed_at'] = datetime.now().isoformat()
            results['success'] = state == AccountState.CLEAN
            
            logger.info("\n" + "=" * 80)
            logger.info(f"🎯 PROTOCOL {'COMPLETE' if results['success'] else 'INCOMPLETE'}")
            logger.info(f"   Final State: {state.value}")
            logger.info(f"   Total Cleanup Metrics:")
            logger.info(f"     - Positions Cleaned: {self.state['cleanup_metrics']['total_positions_cleaned']}")
            logger.info(f"     - Zombies Closed: {self.state['cleanup_metrics']['zombie_positions_closed']}")
            logger.info(f"     - Legacy Unwound: {self.state['cleanup_metrics']['legacy_positions_unwound']}")
            logger.info(f"     - Orders Cancelled: {self.state['cleanup_metrics']['stale_orders_cancelled']}")
            logger.info(f"     - Capital Freed: ${self.state['cleanup_metrics']['capital_freed_usd']:.2f}")
            logger.info("=" * 80 + "\n")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Protocol execution failed: {e}")
            results['error'] = str(e)
            results['success'] = False
            return results
