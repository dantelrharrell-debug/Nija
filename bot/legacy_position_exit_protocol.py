#!/usr/bin/env python3
"""
LEGACY POSITION EXIT PROTOCOL
==============================
Implements a 4-phase protocol to clean platform and gradually unwind legacy positions.

PHASES:
1. Position Classification - Categorize positions (Strategy-Aligned, Legacy, Zombie)
2. Order Cleanup - Cancel stale orders to free locked capital
3. Controlled Exit Engine - Execute gradual unwinding with 4 rules
4. Clean State Verification - Verify compliance and mark account state

GRADUAL UNWINDING:
- Legacy positions unwound 25% per cycle over 4 cycles
- State persists across restarts
- Platform-first execution mode
- User background mode (silent)

NEW REQUIREMENTS (Phased Rollout):
- Step 1: Platform First (dry run → cleanup → verify CLEAN → enable trading)
- Step 2: Users Background Mode (25% gradual unwind, no announcements)
- Step 3: Dashboard Metrics (progress %, positions remaining, capital freed, zombie count)
- Step 4: Capital Minimum Lock (accounts < $100 → copy-only mode)
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, asdict

logger = logging.getLogger("nija.legacy_exit")


class PositionCategory(Enum):
    """Position classification categories"""
    STRATEGY_ALIGNED = "STRATEGY_ALIGNED"  # Category A: Let strategy manage
    LEGACY_NON_COMPLIANT = "LEGACY_NON_COMPLIANT"  # Category B: Gradual 25% unwind
    ZOMBIE = "ZOMBIE"  # Category C: Immediate market close


class CleanState(Enum):
    """Account clean state status"""
    CLEAN = "CLEAN"
    NEEDS_CLEANUP = "NEEDS_CLEANUP"
    IN_PROGRESS = "IN_PROGRESS"
    ERROR = "ERROR"


class ExecutionMode(Enum):
    """Protocol execution modes"""
    PLATFORM_FIRST = "PLATFORM_FIRST"  # Step 1: Platform account only
    USER_BACKGROUND = "USER_BACKGROUND"  # Step 2: User accounts silently
    FULL = "FULL"  # All accounts


@dataclass
class PositionInfo:
    """Position information"""
    symbol: str
    size_usd: float
    category: PositionCategory
    entry_price: float
    current_price: float
    pnl: float
    is_zombie: bool = False
    is_dust: bool = False
    is_over_cap: bool = False
    unwind_progress: float = 0.0  # 0.0 to 1.0 (0% to 100%)
    unwind_cycle: int = 0  # Which cycle of unwinding (1-4)


@dataclass
class CleanupMetrics:
    """Cleanup metrics for dashboard"""
    total_positions_cleaned: int = 0
    zombie_positions_closed: int = 0
    legacy_positions_unwound: int = 0
    stale_orders_cancelled: int = 0
    capital_freed_usd: float = 0.0
    cleanup_progress_pct: float = 0.0
    positions_remaining: int = 0
    zombie_count: int = 0


@dataclass
class ProtocolState:
    """Persistent state across bot restarts"""
    last_run_timestamp: str
    execution_mode: str
    platform_clean: bool
    users_cleanup_progress: Dict[str, float]  # user_id -> progress (0.0-1.0)
    position_unwind_state: Dict[str, Dict]  # symbol -> {cycle, progress}
    total_cycles_completed: int
    metrics: Dict
    account_state: str  # CLEAN or NEEDS_CLEANUP


class LegacyPositionExitProtocol:
    """
    Legacy Position Exit Protocol - 4-Phase System
    
    Implements gradual unwinding of legacy positions with state persistence.
    Supports platform-first execution and user background mode.
    """
    
    def __init__(self,
                 broker_integration,
                 dust_threshold_pct: float = 0.01,  # 1% of account balance
                 max_positions: int = 8,
                 order_stale_minutes: int = 30,
                 unwind_pct_per_cycle: float = 0.25,  # 25% per cycle
                 dry_run: bool = False,
                 execution_mode: ExecutionMode = ExecutionMode.FULL,
                 data_dir: str = "./data"):
        """
        Initialize Legacy Position Exit Protocol.
        
        Args:
            broker_integration: Broker integration instance
            dust_threshold_pct: Dust threshold as % of account balance (default 1%)
            max_positions: Maximum allowed positions
            order_stale_minutes: Minutes before order considered stale
            unwind_pct_per_cycle: Percentage to unwind per cycle (default 25%)
            dry_run: If True, log actions but don't execute
            execution_mode: Platform-first, user-background, or full
            data_dir: Directory for state persistence
        """
        self.broker = broker_integration
        self.dust_threshold_pct = dust_threshold_pct
        self.max_positions = max_positions
        self.order_stale_minutes = order_stale_minutes
        self.unwind_pct_per_cycle = unwind_pct_per_cycle
        self.dry_run = dry_run
        self.execution_mode = execution_mode
        
        # State persistence
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.state_file = self.data_dir / "legacy_exit_protocol_state.json"
        
        # Metrics
        self.metrics = CleanupMetrics()
        
        # Load or initialize state
        self.state = self._load_state()
        
        logger.info("🔄 LEGACY POSITION EXIT PROTOCOL INITIALIZED")
        logger.info(f"   Dust Threshold: {dust_threshold_pct*100}% of account balance")
        logger.info(f"   Max Positions: {max_positions}")
        logger.info(f"   Unwind Rate: {unwind_pct_per_cycle*100}% per cycle")
        logger.info(f"   Execution Mode: {execution_mode.value}")
        logger.info(f"   Dry Run: {dry_run}")
    
    def _load_state(self) -> ProtocolState:
        """Load protocol state from disk"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                
                # Convert metrics dict to CleanupMetrics
                metrics_dict = data.get('metrics', {})
                metrics = CleanupMetrics(**metrics_dict) if metrics_dict else CleanupMetrics()
                
                state = ProtocolState(
                    last_run_timestamp=data.get('last_run_timestamp', ''),
                    execution_mode=data.get('execution_mode', ExecutionMode.FULL.value),
                    platform_clean=data.get('platform_clean', False),
                    users_cleanup_progress=data.get('users_cleanup_progress', {}),
                    position_unwind_state=data.get('position_unwind_state', {}),
                    total_cycles_completed=data.get('total_cycles_completed', 0),
                    metrics=asdict(metrics),
                    account_state=data.get('account_state', CleanState.NEEDS_CLEANUP.value)
                )
                
                # Update metrics from state
                self.metrics = metrics
                
                logger.info(f"📂 Loaded protocol state from {self.state_file}")
                logger.info(f"   Platform Clean: {state.platform_clean}")
                logger.info(f"   Cycles Completed: {state.total_cycles_completed}")
                logger.info(f"   Account State: {state.account_state}")
                
                return state
            except Exception as e:
                logger.error(f"Failed to load state: {e}, initializing new state")
        
        # Initialize new state
        return ProtocolState(
            last_run_timestamp=datetime.now().isoformat(),
            execution_mode=self.execution_mode.value,
            platform_clean=False,
            users_cleanup_progress={},
            position_unwind_state={},
            total_cycles_completed=0,
            metrics=asdict(self.metrics),
            account_state=CleanState.NEEDS_CLEANUP.value
        )
    
    def _save_state(self):
        """Save protocol state to disk"""
        try:
            # Update metrics in state
            self.state.metrics = asdict(self.metrics)
            
            state_dict = asdict(self.state)
            
            # Atomic write
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state_dict, f, indent=2)
            
            temp_file.replace(self.state_file)
            logger.debug(f"💾 Saved protocol state to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def _get_account_balance(self, account_id: Optional[str] = None) -> float:
        """Get account balance in USD"""
        try:
            if account_id:
                balance = self.broker.get_balance(account_id)
            else:
                balance = self.broker.get_balance()
            
            return float(balance.get('total_usd', 0))
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0.0
    
    def _get_dust_threshold_usd(self, account_id: Optional[str] = None) -> float:
        """Calculate dust threshold in USD based on account balance"""
        balance = self._get_account_balance(account_id)
        threshold = balance * self.dust_threshold_pct
        return max(threshold, 1.0)  # Minimum $1
    
    def _get_min_notional(self, symbol: str, account_id: Optional[str] = None) -> float:
        """
        Get minimum notional size for a symbol/exchange.
        
        Args:
            symbol: Trading symbol (e.g., BTC-USD)
            account_id: Account ID (for exchange-specific minimums)
            
        Returns:
            Minimum notional size in USD
        """
        # Exchange-specific minimums (from NIJA codebase patterns)
        # See: bot/minimum_notional_guard.py, bot/capital_tier_scaling.py
        
        # Try to get broker-specific minimum
        try:
            if hasattr(self.broker, 'get_min_notional'):
                min_notional = self.broker.get_min_notional(symbol)
                if min_notional and min_notional > 0:
                    return float(min_notional)
        except:
            pass
        
        # Fallback to exchange defaults based on broker type
        try:
            broker_type = getattr(self.broker, 'name', 'unknown').lower()
            
            # Exchange minimums from codebase
            exchange_minimums = {
                'kraken': 10.0,
                'binance': 10.0,
                'okx': 10.0,
                'coinbase': 2.0,
                'alpaca': 1.0
            }
            
            return exchange_minimums.get(broker_type, 5.0)  # Default $5
            
        except:
            # Safe default
            return 5.0
    
    def _get_positions(self, account_id: Optional[str] = None) -> List[Dict]:
        """Get all positions for account"""
        try:
            if account_id:
                positions = self.broker.get_positions(account_id)
            else:
                positions = self.broker.get_positions()
            
            return positions if positions else []
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def _get_open_orders(self, account_id: Optional[str] = None) -> List[Dict]:
        """Get all open orders for account"""
        try:
            if account_id:
                orders = self.broker.get_open_orders(account_id)
            else:
                orders = self.broker.get_open_orders()
            
            return orders if orders else []
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []
    
    # =========================================================================
    # PHASE 1: POSITION CLASSIFICATION
    # =========================================================================
    
    def classify_position(self, position: Dict, account_balance: float) -> PositionInfo:
        """
        Classify a position into Category A, B, or C.
        
        Category A (Strategy-Aligned): Positions the current strategy would hold
        Category B (Legacy Non-Compliant): Old positions that need gradual unwinding
        Category C (Zombie): Positions that can't be managed (immediate close)
        
        Args:
            position: Position dictionary from broker
            account_balance: Account balance in USD
            
        Returns:
            PositionInfo with classification
        """
        symbol = position.get('symbol', position.get('pair', 'UNKNOWN'))
        size_usd = float(position.get('size_usd', position.get('value_usd', 0)))
        entry_price = float(position.get('entry_price', position.get('avg_price', 0)))
        current_price = float(position.get('current_price', position.get('price', entry_price)))
        pnl = float(position.get('pnl', 0))
        
        # Calculate thresholds
        dust_threshold = self._get_dust_threshold_usd()
        
        # Check if zombie (can't get price or data)
        is_zombie = (current_price <= 0 or entry_price <= 0 or 
                     symbol == 'UNKNOWN' or not symbol)
        
        # Check if dust
        is_dust = size_usd < dust_threshold
        
        # Get unwind state if exists
        unwind_state = self.state.position_unwind_state.get(symbol, {})
        unwind_progress = unwind_state.get('progress', 0.0)
        unwind_cycle = unwind_state.get('cycle', 0)
        
        # Determine category
        if is_zombie:
            category = PositionCategory.ZOMBIE
        elif is_dust:
            # Dust positions are legacy (will be closed immediately)
            category = PositionCategory.LEGACY_NON_COMPLIANT
        elif unwind_progress > 0:
            # Already unwinding = legacy
            category = PositionCategory.LEGACY_NON_COMPLIANT
        else:
            # For now, assume positions are strategy-aligned unless marked otherwise
            # In production, check against strategy rules
            category = PositionCategory.STRATEGY_ALIGNED
        
        return PositionInfo(
            symbol=symbol,
            size_usd=size_usd,
            category=category,
            entry_price=entry_price,
            current_price=current_price,
            pnl=pnl,
            is_zombie=is_zombie,
            is_dust=is_dust,
            is_over_cap=False,  # Will be set in Phase 3
            unwind_progress=unwind_progress,
            unwind_cycle=unwind_cycle
        )
    
    def phase1_classify_positions(self, account_id: Optional[str] = None) -> Dict[str, List[PositionInfo]]:
        """
        Phase 1: Classify all positions into categories.
        Non-destructive - only classification, no trading.
        
        Returns:
            Dict with lists of positions by category
        """
        logger.info("=" * 80)
        logger.info("PHASE 1: POSITION CLASSIFICATION")
        logger.info("=" * 80)
        
        positions = self._get_positions(account_id)
        balance = self._get_account_balance(account_id)
        
        classified = {
            'strategy_aligned': [],
            'legacy_non_compliant': [],
            'zombie': []
        }
        
        for pos in positions:
            pos_info = self.classify_position(pos, balance)
            
            if pos_info.category == PositionCategory.STRATEGY_ALIGNED:
                classified['strategy_aligned'].append(pos_info)
            elif pos_info.category == PositionCategory.LEGACY_NON_COMPLIANT:
                classified['legacy_non_compliant'].append(pos_info)
            elif pos_info.category == PositionCategory.ZOMBIE:
                classified['zombie'].append(pos_info)
        
        logger.info(f"📊 Classification Results:")
        logger.info(f"   Category A (Strategy-Aligned): {len(classified['strategy_aligned'])} positions")
        logger.info(f"   Category B (Legacy Non-Compliant): {len(classified['legacy_non_compliant'])} positions")
        logger.info(f"   Category C (Zombie): {len(classified['zombie'])} positions")
        
        return classified
    
    # =========================================================================
    # PHASE 2: ORDER CLEANUP
    # =========================================================================
    
    def phase2_order_cleanup(self, account_id: Optional[str] = None) -> Tuple[int, float]:
        """
        Phase 2: Cancel stale orders to free locked capital.
        
        Orders older than order_stale_minutes are cancelled.
        
        Returns:
            Tuple of (orders_cancelled, capital_freed_usd)
        """
        logger.info("=" * 80)
        logger.info("PHASE 2: ORDER CLEANUP")
        logger.info("=" * 80)
        
        orders = self._get_open_orders(account_id)
        stale_cutoff = datetime.now() - timedelta(minutes=self.order_stale_minutes)
        
        orders_cancelled = 0
        capital_freed = 0.0
        
        for order in orders:
            order_time_str = order.get('created_at', order.get('timestamp', ''))
            try:
                order_time = datetime.fromisoformat(order_time_str.replace('Z', '+00:00'))
            except:
                # If can't parse, assume stale
                order_time = datetime.min
            
            if order_time < stale_cutoff:
                order_id = order.get('order_id', order.get('id', 'UNKNOWN'))
                order_value = float(order.get('value_usd', order.get('size', 0)))
                
                logger.info(f"🗑️  Cancelling stale order: {order_id} (${order_value:.2f})")
                
                if not self.dry_run:
                    try:
                        if account_id:
                            self.broker.cancel_order(order_id, account_id)
                        else:
                            self.broker.cancel_order(order_id)
                        
                        orders_cancelled += 1
                        capital_freed += order_value
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order_id}: {e}")
                else:
                    orders_cancelled += 1
                    capital_freed += order_value
        
        logger.info(f"✅ Phase 2 Complete:")
        logger.info(f"   Orders Cancelled: {orders_cancelled}")
        logger.info(f"   Capital Freed: ${capital_freed:.2f}")
        
        # Update metrics
        self.metrics.stale_orders_cancelled += orders_cancelled
        self.metrics.capital_freed_usd += capital_freed
        
        return orders_cancelled, capital_freed
    
    # =========================================================================
    # PHASE 3: CONTROLLED EXIT ENGINE
    # =========================================================================
    
    def phase3_controlled_exit(self, classified: Dict[str, List[PositionInfo]], 
                               account_id: Optional[str] = None) -> Dict[str, int]:
        """
        Phase 3: Execute controlled exits based on 4 rules.
        
        Rule 1: Dust (< 1% account) → immediate close
        Rule 2: Over-cap → worst performing first
        Rule 3: Legacy → gradual 25% unwind over 4 cycles
        Rule 4: Zombie → try once, log if fails, don't halt
        
        Returns:
            Dict with counts of each exit type
        """
        logger.info("=" * 80)
        logger.info("PHASE 3: CONTROLLED EXIT ENGINE")
        logger.info("=" * 80)
        
        exits = {
            'dust_closed': 0,
            'over_cap_closed': 0,
            'legacy_unwound': 0,
            'zombie_closed': 0
        }
        
        # Rule 4: Zombie positions - try to close, don't halt on failure
        for pos_info in classified['zombie']:
            logger.info(f"👻 Closing zombie position: {pos_info.symbol}")
            
            if not self.dry_run:
                try:
                    if account_id:
                        self.broker.close_position(pos_info.symbol, account_id)
                    else:
                        self.broker.close_position(pos_info.symbol)
                    
                    exits['zombie_closed'] += 1
                    self.metrics.zombie_positions_closed += 1
                    self.metrics.total_positions_cleaned += 1
                    self.metrics.zombie_count = max(0, self.metrics.zombie_count - 1)
                except Exception as e:
                    logger.warning(f"Failed to close zombie {pos_info.symbol}: {e} (continuing...)")
            else:
                exits['zombie_closed'] += 1
        
        # Rule 1: Dust positions - immediate close
        for pos_info in classified['legacy_non_compliant']:
            if pos_info.is_dust:
                logger.info(f"💨 Closing dust position: {pos_info.symbol} (${pos_info.size_usd:.2f})")
                
                if not self.dry_run:
                    try:
                        if account_id:
                            self.broker.close_position(pos_info.symbol, account_id)
                        else:
                            self.broker.close_position(pos_info.symbol)
                        
                        exits['dust_closed'] += 1
                        self.metrics.total_positions_cleaned += 1
                        self.metrics.capital_freed_usd += pos_info.size_usd
                    except Exception as e:
                        logger.error(f"Failed to close dust position {pos_info.symbol}: {e}")
                else:
                    exits['dust_closed'] += 1
        
        # Rule 2: Over-cap - close worst performing first
        all_positions = (classified['strategy_aligned'] + 
                        [p for p in classified['legacy_non_compliant'] if not p.is_dust])
        
        if len(all_positions) > self.max_positions:
            logger.info(f"⚠️  Over position cap: {len(all_positions)} > {self.max_positions}")
            
            # Sort by PnL (worst first)
            all_positions.sort(key=lambda p: p.pnl)
            
            positions_to_close = len(all_positions) - self.max_positions
            for pos_info in all_positions[:positions_to_close]:
                logger.info(f"📉 Closing over-cap position: {pos_info.symbol} (PnL: ${pos_info.pnl:.2f})")
                
                if not self.dry_run:
                    try:
                        if account_id:
                            self.broker.close_position(pos_info.symbol, account_id)
                        else:
                            self.broker.close_position(pos_info.symbol)
                        
                        exits['over_cap_closed'] += 1
                        self.metrics.total_positions_cleaned += 1
                        self.metrics.capital_freed_usd += pos_info.size_usd
                    except Exception as e:
                        logger.error(f"Failed to close over-cap position {pos_info.symbol}: {e}")
                else:
                    exits['over_cap_closed'] += 1
        
        # Rule 3: Legacy positions - gradual 25% unwind
        # NEW REQUIREMENT: Do NOT allow 25% unwind to violate min notional size
        for pos_info in classified['legacy_non_compliant']:
            if not pos_info.is_dust and pos_info.unwind_progress < 1.0:
                # Calculate amount to unwind this cycle
                remaining = 1.0 - pos_info.unwind_progress
                to_unwind = min(remaining, self.unwind_pct_per_cycle)
                
                unwind_size_usd = pos_info.size_usd * to_unwind
                remaining_after_unwind = pos_info.size_usd * (1 - to_unwind)
                
                # Get minimum notional size for this symbol/exchange
                min_notional = self._get_min_notional(pos_info.symbol, account_id)
                
                # Check if remaining position would violate minimum notional
                if remaining_after_unwind < min_notional and remaining_after_unwind > 0:
                    logger.warning(f"⚠️  Unwind would violate min notional for {pos_info.symbol}")
                    logger.warning(f"   Remaining after {to_unwind*100:.0f}% unwind: ${remaining_after_unwind:.2f}")
                    logger.warning(f"   Minimum notional required: ${min_notional:.2f}")
                    
                    # Strategy: Close entire position instead of partial unwind
                    if remaining < 0.5:  # If < 50% remains, close everything
                        logger.info(f"   Closing entire position instead (less than 50% remains)")
                        
                        if not self.dry_run:
                            try:
                                if account_id:
                                    self.broker.close_position(pos_info.symbol, account_id)
                                else:
                                    self.broker.close_position(pos_info.symbol)
                                
                                # Mark as fully unwound
                                self.state.position_unwind_state[pos_info.symbol] = {
                                    'progress': 1.0,
                                    'cycle': pos_info.unwind_cycle + 1
                                }
                                
                                exits['legacy_unwound'] += 1
                                self.metrics.legacy_positions_unwound += 1
                                self.metrics.total_positions_cleaned += 1
                                self.metrics.capital_freed_usd += pos_info.size_usd
                                
                                logger.info(f"✅ Position {pos_info.symbol} fully closed (min notional enforcement)")
                            except Exception as e:
                                logger.error(f"Failed to close legacy position {pos_info.symbol}: {e}")
                        else:
                            exits['legacy_unwound'] += 1
                    else:
                        # Skip this cycle - wait for next cycle when remaining is smaller
                        logger.info(f"   Skipping unwind this cycle (would violate min notional)")
                        logger.info(f"   Will attempt again in next cycle")
                    
                    continue  # Skip to next position
                
                logger.info(f"🔄 Unwinding legacy position: {pos_info.symbol}")
                logger.info(f"   Current: ${pos_info.size_usd:.2f}, Unwinding: {to_unwind*100:.0f}% (${unwind_size_usd:.2f})")
                logger.info(f"   Remaining after unwind: ${remaining_after_unwind:.2f} (min notional: ${min_notional:.2f})")
                logger.info(f"   Cycle: {pos_info.unwind_cycle + 1}/4, Progress: {(pos_info.unwind_progress + to_unwind)*100:.0f}%")
                
                if not self.dry_run:
                    try:
                        # Partial close
                        if account_id:
                            self.broker.close_position_partial(pos_info.symbol, to_unwind, account_id)
                        else:
                            self.broker.close_position_partial(pos_info.symbol, to_unwind)
                        
                        # Update unwind state
                        new_progress = pos_info.unwind_progress + to_unwind
                        new_cycle = pos_info.unwind_cycle + 1
                        
                        self.state.position_unwind_state[pos_info.symbol] = {
                            'progress': new_progress,
                            'cycle': new_cycle
                        }
                        
                        exits['legacy_unwound'] += 1
                        self.metrics.legacy_positions_unwound += 1
                        self.metrics.capital_freed_usd += unwind_size_usd
                        
                        if new_progress >= 1.0:
                            logger.info(f"✅ Position {pos_info.symbol} fully unwound")
                            self.metrics.total_positions_cleaned += 1
                    except Exception as e:
                        logger.error(f"Failed to unwind legacy position {pos_info.symbol}: {e}")
                else:
                    exits['legacy_unwound'] += 1
        
        logger.info(f"✅ Phase 3 Complete:")
        logger.info(f"   Dust Closed: {exits['dust_closed']}")
        logger.info(f"   Over-Cap Closed: {exits['over_cap_closed']}")
        logger.info(f"   Legacy Unwound: {exits['legacy_unwound']}")
        logger.info(f"   Zombie Closed: {exits['zombie_closed']}")
        
        return exits
    
    # =========================================================================
    # PHASE 4: CLEAN STATE VERIFICATION
    # =========================================================================
    
    def phase4_verify_clean_state(self, account_id: Optional[str] = None) -> CleanState:
        """
        Phase 4: Verify account is in clean state.
        
        Checks:
        - Positions <= cap
        - No zombie positions
        - All positions registered
        - No stale orders
        
        Returns:
            CleanState enum value
        """
        logger.info("=" * 80)
        logger.info("PHASE 4: CLEAN STATE VERIFICATION")
        logger.info("=" * 80)
        
        positions = self._get_positions(account_id)
        orders = self._get_open_orders(account_id)
        balance = self._get_account_balance(account_id)
        
        # Count zombies
        zombie_count = 0
        for pos in positions:
            pos_info = self.classify_position(pos, balance)
            if pos_info.is_zombie:
                zombie_count += 1
        
        # Count stale orders
        stale_cutoff = datetime.now() - timedelta(minutes=self.order_stale_minutes)
        stale_orders = 0
        for order in orders:
            order_time_str = order.get('created_at', order.get('timestamp', ''))
            try:
                order_time = datetime.fromisoformat(order_time_str.replace('Z', '+00:00'))
                if order_time < stale_cutoff:
                    stale_orders += 1
            except:
                stale_orders += 1
        
        # Verification checks
        checks = {
            'positions_under_cap': len(positions) <= self.max_positions,
            'no_zombies': zombie_count == 0,
            'no_stale_orders': stale_orders == 0
        }
        
        logger.info(f"🔍 Verification Results:")
        logger.info(f"   Positions: {len(positions)}/{self.max_positions} {'✅' if checks['positions_under_cap'] else '❌'}")
        logger.info(f"   Zombie Count: {zombie_count} {'✅' if checks['no_zombies'] else '❌'}")
        logger.info(f"   Stale Orders: {stale_orders} {'✅' if checks['no_stale_orders'] else '❌'}")
        
        # Update metrics
        self.metrics.positions_remaining = len(positions)
        self.metrics.zombie_count = zombie_count
        
        # Determine state
        if all(checks.values()):
            state = CleanState.CLEAN
            logger.info("✅ ACCOUNT STATE: CLEAN")
        else:
            state = CleanState.NEEDS_CLEANUP
            logger.info("⚠️  ACCOUNT STATE: NEEDS CLEANUP")
        
        return state
    
    # =========================================================================
    # FULL PROTOCOL EXECUTION
    # =========================================================================
    
    def run_full_protocol(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run all 4 phases of the protocol.
        
        Returns:
            Dict with results from all phases
        """
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("🚀 STARTING LEGACY POSITION EXIT PROTOCOL")
        logger.info("=" * 80)
        
        results = {
            'start_time': datetime.now().isoformat(),
            'execution_mode': self.execution_mode.value,
            'account_id': account_id or 'platform',
            'phases': {}
        }
        
        # Phase 1: Classification
        classified = self.phase1_classify_positions(account_id)
        results['phases']['phase1'] = {
            'strategy_aligned': len(classified['strategy_aligned']),
            'legacy_non_compliant': len(classified['legacy_non_compliant']),
            'zombie': len(classified['zombie'])
        }
        
        # Phase 2: Order Cleanup
        orders_cancelled, capital_freed = self.phase2_order_cleanup(account_id)
        results['phases']['phase2'] = {
            'orders_cancelled': orders_cancelled,
            'capital_freed_usd': capital_freed
        }
        
        # Phase 3: Controlled Exit
        exits = self.phase3_controlled_exit(classified, account_id)
        results['phases']['phase3'] = exits
        
        # Phase 4: Verification
        clean_state = self.phase4_verify_clean_state(account_id)
        results['phases']['phase4'] = {
            'state': clean_state.value,
            'positions_remaining': self.metrics.positions_remaining,
            'zombie_count': self.metrics.zombie_count
        }
        
        # Calculate cleanup progress
        total_positions_start = (len(classified['strategy_aligned']) + 
                                len(classified['legacy_non_compliant']) + 
                                len(classified['zombie']))
        
        if total_positions_start > 0:
            positions_cleaned = (exits['dust_closed'] + exits['over_cap_closed'] + 
                               exits['zombie_closed'])
            self.metrics.cleanup_progress_pct = (positions_cleaned / total_positions_start) * 100
        
        # Update state
        self.state.last_run_timestamp = datetime.now().isoformat()
        self.state.total_cycles_completed += 1
        self.state.account_state = clean_state.value
        
        if account_id is None and clean_state == CleanState.CLEAN:
            self.state.platform_clean = True
        
        # Save state
        self._save_state()
        
        elapsed = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info(f"✅ PROTOCOL COMPLETE")
        logger.info(f"   Execution Time: {elapsed:.2f}s")
        logger.info(f"   Account State: {clean_state.value}")
        logger.info(f"   Total Cycles: {self.state.total_cycles_completed}")
        logger.info("=" * 80)
        
        results['end_time'] = datetime.now().isoformat()
        results['elapsed_seconds'] = elapsed
        results['metrics'] = asdict(self.metrics)
        results['state'] = clean_state.value
        
        return results
    
    def verify_only(self, account_id: Optional[str] = None) -> CleanState:
        """
        Run verification only (Phase 4) without making changes.
        
        Returns:
            CleanState enum value
        """
        logger.info("🔍 RUNNING VERIFICATION ONLY")
        return self.phase4_verify_clean_state(account_id)
    
    def get_metrics(self) -> CleanupMetrics:
        """Get current cleanup metrics for dashboard"""
        return self.metrics
    
    def is_platform_clean(self) -> bool:
        """Check if platform account is clean"""
        return self.state.platform_clean
    
    def should_enable_trading(self) -> bool:
        """
        Check if trading should be enabled.
        
        For platform-first mode: Only enable if platform is clean.
        """
        if self.execution_mode == ExecutionMode.PLATFORM_FIRST:
            return self.state.platform_clean
        return True
