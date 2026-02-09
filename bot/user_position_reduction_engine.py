"""
NIJA User Position Reduction Engine
===================================

Production-ready engine that enforces per-user position caps and automatically
unwinds oversized portfolios and dust positions.

Key Features:
- Enforce maximum positions per user (default: 8, configurable)
- Identify and close dust positions (< $1 USD threshold, configurable)
- Auto-unwind oversized portfolios using size-based ranking (smallest first)
- Handle both NIJA-managed positions AND existing holdings
- Track closure outcomes: WIN, LOSS, BREAKEVEN
- Comprehensive logging and error handling

Integration Points:
- MultiAccountBrokerManager: Get user brokers
- PortfolioStateManager: Track user portfolios
- TradeLedger: Record all closures
- Broker APIs: Execute position closes
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.position_reduction")


class PositionOutcome(Enum):
    """Outcome categories for closed positions"""
    WIN = "WIN"           # Closed with profit (> +1%)
    LOSS = "LOSS"         # Closed with loss (< -1%)
    BREAKEVEN = "BREAKEVEN"  # Closed at or near entry (-1% to +1%)


class UserPositionReductionEngine:
    """
    Enforces position limits and cleans up dust positions for users.
    
    This engine:
    1. Identifies dust positions (< threshold USD)
    2. Enforces position cap (default: 8 max)
    3. Ranks and closes excess positions (smallest first)
    4. Tracks outcomes (WIN/LOSS/BREAKEVEN)
    5. Logs all actions to trade ledger
    """
    
    # Default thresholds
    DEFAULT_MAX_POSITIONS = 8
    DEFAULT_DUST_THRESHOLD_USD = 1.00
    BREAKEVEN_THRESHOLD_PCT = 0.01  # ±1% is considered breakeven
    
    # Safety: Rate limit position closures to prevent API spam
    CLOSURE_DELAY_SECONDS = 1.0  # 1 second delay between closures
    
    def __init__(
        self,
        multi_account_broker_manager,
        portfolio_state_manager,
        trade_ledger=None,
        max_positions: int = DEFAULT_MAX_POSITIONS,
        dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD
    ):
        """
        Initialize position reduction engine.
        
        Args:
            multi_account_broker_manager: Manager for user brokers
            portfolio_state_manager: Manager for portfolio states
            trade_ledger: Trade ledger for recording closures (optional)
            max_positions: Maximum positions allowed per user
            dust_threshold_usd: USD threshold for dust positions
        """
        self.broker_manager = multi_account_broker_manager
        self.portfolio_manager = portfolio_state_manager
        self.trade_ledger = trade_ledger
        self.max_positions = max_positions
        self.dust_threshold_usd = dust_threshold_usd
        
        logger.info(f"Position Reduction Engine initialized")
        logger.info(f"  Max positions: {max_positions}")
        logger.info(f"  Dust threshold: ${dust_threshold_usd:.2f} USD")
    
    def get_user_positions(self, user_id: str, broker_type: str) -> List[Dict]:
        """
        Get all positions for a user from their broker.
        
        Args:
            user_id: User identifier
            broker_type: Broker type (e.g., 'kraken', 'coinbase')
        
        Returns:
            List of position dictionaries with standardized format
        """
        try:
            # Get broker for user
            broker = self.broker_manager.get_user_broker(user_id, broker_type)
            if not broker:
                logger.warning(f"No broker found for user {user_id} on {broker_type}")
                return []
            
            # Check if broker is connected
            if not broker.connected:
                logger.warning(f"Broker not connected for user {user_id} on {broker_type}")
                return []
            
            # Get positions from broker
            raw_positions = broker.get_positions()
            if not raw_positions:
                return []
            
            # Standardize position format
            positions = []
            for pos in raw_positions:
                # Calculate position size in USD
                current_price = pos.get('current_price', pos.get('mark_price', 0.0))
                quantity = abs(pos.get('quantity', pos.get('size', 0.0)))
                size_usd = current_price * quantity
                
                # Calculate P&L
                entry_price = pos.get('entry_price', pos.get('average_price', current_price))
                pnl_usd = (current_price - entry_price) * quantity
                pnl_pct = (pnl_usd / (entry_price * quantity)) if (entry_price * quantity) > 0 else 0.0
                
                positions.append({
                    'symbol': pos.get('symbol', pos.get('product_id', 'UNKNOWN')),
                    'quantity': quantity,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'size_usd': size_usd,
                    'pnl_usd': pnl_usd,
                    'pnl_pct': pnl_pct,
                    'position_id': pos.get('position_id', pos.get('id')),
                    'side': pos.get('side', 'long'),
                    'raw_position': pos  # Keep original for reference
                })
            
            return positions
        
        except Exception as e:
            logger.error(f"Error getting positions for {user_id}: {e}")
            return []
    
    def identify_dust_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify positions below dust threshold.
        
        Args:
            positions: List of position dictionaries
        
        Returns:
            List of dust positions to close
        """
        dust = []
        
        for pos in positions:
            if pos['size_usd'] < self.dust_threshold_usd:
                dust.append({
                    **pos,
                    'cleanup_type': 'DUST',
                    'reason': f"Dust position (${pos['size_usd']:.2f} < ${self.dust_threshold_usd:.2f})"
                })
        
        logger.info(f"Identified {len(dust)} dust positions")
        return dust
    
    def identify_cap_excess_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify positions to close when over cap (after dust cleanup).
        
        Ranking strategy:
        1. Smallest USD value first (minimize capital impact)
        2. Worst P&L if tied on size
        
        Args:
            positions: List of non-dust positions
        
        Returns:
            List of positions to close to enforce cap
        """
        if len(positions) <= self.max_positions:
            return []
        
        # Rank by size (smallest first), then by P&L (worst first)
        ranked = sorted(positions, key=lambda p: (p['size_usd'], p['pnl_pct']))
        
        # Determine how many to close
        excess_count = len(positions) - self.max_positions
        
        cap_excess = []
        for pos in ranked[:excess_count]:
            cap_excess.append({
                **pos,
                'cleanup_type': 'CAP_EXCEEDED',
                'reason': f"Position cap exceeded ({len(positions)}/{self.max_positions})"
            })
        
        logger.info(f"Identified {len(cap_excess)} cap excess positions")
        return cap_excess
    
    def categorize_outcome(self, pnl_pct: float) -> PositionOutcome:
        """
        Categorize position outcome based on P&L.
        
        Args:
            pnl_pct: P&L percentage (e.g., 0.05 = +5%)
        
        Returns:
            Outcome category: WIN, LOSS, or BREAKEVEN
        """
        if pnl_pct > self.BREAKEVEN_THRESHOLD_PCT:
            return PositionOutcome.WIN
        elif pnl_pct < -self.BREAKEVEN_THRESHOLD_PCT:
            return PositionOutcome.LOSS
        else:
            return PositionOutcome.BREAKEVEN
    
    def close_position(
        self,
        user_id: str,
        broker_type: str,
        position: Dict,
        dry_run: bool = False
    ) -> Dict:
        """
        Close a single position.
        
        Args:
            user_id: User identifier
            broker_type: Broker type
            position: Position dictionary
            dry_run: If True, preview only without executing
        
        Returns:
            Closure result dictionary
        """
        symbol = position['symbol']
        outcome = self.categorize_outcome(position['pnl_pct'])
        
        if dry_run:
            logger.info(f"[DRY RUN] Would close {symbol} for {user_id}: {outcome.value}")
            return {
                'success': True,
                'dry_run': True,
                'symbol': symbol,
                'outcome': outcome.value,
                'pnl_usd': position['pnl_usd'],
                'reason': position['reason']
            }
        
        try:
            # Get broker
            broker = self.broker_manager.get_user_broker(user_id, broker_type)
            if not broker or not broker.connected:
                raise Exception(f"Broker not available for {user_id}")
            
            # Close position via broker
            # Try close_position first, fallback to place_market_order
            if hasattr(broker, 'close_position'):
                result = broker.close_position(symbol)
            else:
                # Use market order to close
                side = 'sell' if position['side'] == 'long' else 'buy'
                result = broker.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=position['quantity']
                )
            
            # Log to trade ledger if available
            if self.trade_ledger:
                try:
                    self.trade_ledger.record_closure(
                        user_id=user_id,
                        symbol=symbol,
                        quantity=position['quantity'],
                        entry_price=position['entry_price'],
                        exit_price=position['current_price'],
                        pnl_usd=position['pnl_usd'],
                        pnl_pct=position['pnl_pct'],
                        outcome=outcome.value,
                        reason=position['reason'],
                        timestamp=datetime.now().isoformat()
                    )
                except Exception as ledger_err:
                    logger.warning(f"Failed to log closure to ledger: {ledger_err}")
            
            logger.info(
                f"✅ Closed {symbol} for {user_id}: "
                f"{outcome.value} | P&L: ${position['pnl_usd']:+.2f} ({position['pnl_pct']:+.2%}) | "
                f"Reason: {position['reason']}"
            )
            
            return {
                'success': True,
                'dry_run': False,
                'symbol': symbol,
                'outcome': outcome.value,
                'pnl_usd': position['pnl_usd'],
                'pnl_pct': position['pnl_pct'],
                'reason': position['reason'],
                'result': result
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to close {symbol} for {user_id}: {e}")
            return {
                'success': False,
                'symbol': symbol,
                'error': str(e),
                'reason': position['reason']
            }
    
    def reduce_user_positions(
        self,
        user_id: str,
        broker_type: str,
        dry_run: bool = False,
        max_positions: Optional[int] = None,
        dust_threshold_usd: Optional[float] = None
    ) -> Dict:
        """
        Reduce positions for a specific user.
        
        This is the main entry point for position reduction.
        
        Args:
            user_id: User identifier
            broker_type: Broker type (e.g., 'kraken')
            dry_run: If True, preview only without executing
            max_positions: Override default max positions
            dust_threshold_usd: Override default dust threshold
        
        Returns:
            Summary dictionary with reduction results
        """
        # Use overrides if provided
        max_pos = max_positions if max_positions is not None else self.max_positions
        dust_thresh = dust_threshold_usd if dust_threshold_usd is not None else self.dust_threshold_usd
        
        logger.info("=" * 80)
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Reducing positions for {user_id}")
        logger.info(f"  Broker: {broker_type}")
        logger.info(f"  Max positions: {max_pos}")
        logger.info(f"  Dust threshold: ${dust_thresh:.2f}")
        logger.info("=" * 80)
        
        # Get current positions
        positions = self.get_user_positions(user_id, broker_type)
        initial_count = len(positions)
        
        if initial_count == 0:
            logger.info(f"No positions found for {user_id}")
            return {
                'user_id': user_id,
                'broker_type': broker_type,
                'initial_positions': 0,
                'final_positions': 0,
                'closed_positions': 0,
                'breakdown': {'dust_closed': 0, 'cap_excess_closed': 0},
                'outcomes': {'wins': 0, 'losses': 0, 'breakeven': 0},
                'capital_impact': {
                    'initial_capital': 0.0,
                    'closed_capital': 0.0,
                    'final_capital': 0.0
                }
            }
        
        initial_capital = sum(p['size_usd'] for p in positions)
        logger.info(f"Initial state: {initial_count} positions, ${initial_capital:.2f} capital")
        
        # Step 1: Identify dust positions
        dust_positions = self.identify_dust_positions(positions)
        
        # Step 2: Identify cap excess (from non-dust positions)
        remaining = [p for p in positions if p['size_usd'] >= dust_thresh]
        cap_excess = []
        if len(remaining) > max_pos:
            # Temporarily update threshold for this call
            old_max = self.max_positions
            self.max_positions = max_pos
            cap_excess = self.identify_cap_excess_positions(remaining)
            self.max_positions = old_max
        
        # Combine positions to close
        to_close = dust_positions + cap_excess
        
        if not to_close:
            logger.info(f"No positions need to be closed for {user_id}")
            return {
                'user_id': user_id,
                'broker_type': broker_type,
                'initial_positions': initial_count,
                'final_positions': initial_count,
                'closed_positions': 0,
                'breakdown': {'dust_closed': 0, 'cap_excess_closed': 0},
                'outcomes': {'wins': 0, 'losses': 0, 'breakeven': 0},
                'capital_impact': {
                    'initial_capital': initial_capital,
                    'closed_capital': 0.0,
                    'final_capital': initial_capital
                }
            }
        
        # Close positions (with error recovery)
        outcomes = {'wins': 0, 'losses': 0, 'breakeven': 0}
        successful_closures = []
        failed_closures = []
        
        logger.info(f"Closing {len(to_close)} positions...")
        
        for i, pos in enumerate(to_close, 1):
            logger.info(f"  [{i}/{len(to_close)}] {pos['symbol']} - ${pos['size_usd']:.2f}")
            
            # Close position
            result = self.close_position(user_id, broker_type, pos, dry_run=dry_run)
            
            if result['success']:
                successful_closures.append(result)
                
                # Track outcome
                outcome = result['outcome']
                if outcome == PositionOutcome.WIN.value:
                    outcomes['wins'] += 1
                elif outcome == PositionOutcome.LOSS.value:
                    outcomes['losses'] += 1
                else:
                    outcomes['breakeven'] += 1
            else:
                failed_closures.append(result)
            
            # Rate limiting: delay between closures
            if i < len(to_close) and not dry_run:
                time.sleep(self.CLOSURE_DELAY_SECONDS)
        
        # Calculate final state
        closed_count = len(successful_closures)
        final_count = initial_count - closed_count
        
        closed_capital = sum(
            p['size_usd'] for p in to_close
            if any(c['symbol'] == p['symbol'] for c in successful_closures)
        )
        final_capital = initial_capital - closed_capital
        
        # Build summary
        summary = {
            'user_id': user_id,
            'broker_type': broker_type,
            'initial_positions': initial_count,
            'final_positions': final_count,
            'closed_positions': closed_count,
            'failed_closures': len(failed_closures),
            'breakdown': {
                'dust_closed': len([p for p in dust_positions if any(c['symbol'] == p['symbol'] for c in successful_closures)]),
                'cap_excess_closed': len([p for p in cap_excess if any(c['symbol'] == p['symbol'] for c in successful_closures)])
            },
            'outcomes': outcomes,
            'capital_impact': {
                'initial_capital': initial_capital,
                'closed_capital': closed_capital,
                'final_capital': final_capital
            },
            'dry_run': dry_run
        }
        
        # Log summary
        logger.info("=" * 80)
        logger.info(f"Position Reduction Summary for {user_id}")
        logger.info("=" * 80)
        logger.info(f"  Positions: {initial_count} → {final_count} ({closed_count} closed)")
        logger.info(f"  Dust closed: {summary['breakdown']['dust_closed']}")
        logger.info(f"  Cap excess closed: {summary['breakdown']['cap_excess_closed']}")
        logger.info(f"  Outcomes: {outcomes['wins']} wins, {outcomes['losses']} losses, {outcomes['breakeven']} breakeven")
        logger.info(f"  Capital: ${initial_capital:.2f} → ${final_capital:.2f}")
        
        if failed_closures:
            logger.warning(f"  ⚠️  {len(failed_closures)} closures failed")
        
        logger.info("=" * 80)
        
        return summary
    
    def preview_reduction(
        self,
        user_id: str,
        broker_type: str,
        max_positions: Optional[int] = None,
        dust_threshold_usd: Optional[float] = None
    ) -> Dict:
        """
        Preview position reduction without executing.
        
        This is a dry-run that shows what would be closed.
        
        Args:
            user_id: User identifier
            broker_type: Broker type
            max_positions: Override default max positions
            dust_threshold_usd: Override default dust threshold
        
        Returns:
            Preview summary (same as reduce_user_positions with dry_run=True)
        """
        return self.reduce_user_positions(
            user_id=user_id,
            broker_type=broker_type,
            dry_run=True,
            max_positions=max_positions,
            dust_threshold_usd=dust_threshold_usd
        )
