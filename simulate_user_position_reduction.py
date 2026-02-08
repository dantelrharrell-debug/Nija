#!/usr/bin/env python3
"""
USER POSITION REDUCTION SIMULATION
===================================
Simulates exactly how user_daivon_frazier's 59 positions and user_tania_gilbert's 54 positions
would reduce to 8 each, showing expected profit/break-even outcomes.

This provides a concrete view of what the deployment actually does:
1. Dust cleanup (positions < $1 USD)
2. Position cap enforcement (reduce to 8 positions max)
3. Profit/loss tracking for each closed position
4. Before/after capital analysis

Usage:
    python3 simulate_user_position_reduction.py
"""

import random
import logging
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from enum import Enum

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger("simulation")


class PositionOutcome(Enum):
    """Outcome categories for closed positions"""
    WIN = "WIN"           # Closed with profit
    LOSS = "LOSS"         # Closed with loss
    BREAKEVEN = "BREAKEVEN"  # Closed at or near entry


class UserPositionSimulation:
    """
    Simulates position reduction for a specific user.
    Models realistic position distribution and cleanup process.
    """
    
    def __init__(self, 
                 user_id: str,
                 initial_position_count: int,
                 max_positions: int = 8,
                 dust_threshold_usd: float = 1.00):
        """
        Initialize simulation for a user.
        
        Args:
            user_id: User identifier (e.g., 'user_daivon_frazier')
            initial_position_count: Starting number of positions
            max_positions: Target position count after cleanup
            dust_threshold_usd: USD threshold for dust positions
        """
        self.user_id = user_id
        self.initial_position_count = initial_position_count
        self.max_positions = max_positions
        self.dust_threshold_usd = dust_threshold_usd
        
        # Tracking metrics
        self.positions = []
        self.dust_positions = []
        self.cap_excess_positions = []
        self.final_positions = []
        self.outcomes = {
            'WIN': [],
            'LOSS': [],
            'BREAKEVEN': []
        }
        
    def generate_realistic_positions(self) -> List[Dict]:
        """
        Generate realistic position distribution.
        
        Models actual user behavior:
        - Most positions are small/dust (70-80%)
        - Some medium positions (15-20%)
        - Few large positions (5-10%)
        - Mix of profits and losses
        """
        symbols = [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'MATIC-USD', 'ADA-USD',
            'DOT-USD', 'AVAX-USD', 'LINK-USD', 'UNI-USD', 'ATOM-USD',
            'XLM-USD', 'ALGO-USD', 'SHIB-USD', 'DOGE-USD', 'LTC-USD',
            'BCH-USD', 'XRP-USD', 'TRX-USD', 'FIL-USD', 'AAVE-USD',
            'COMP-USD', 'SUSHI-USD', 'CRV-USD', 'SNX-USD', 'YFI-USD',
            'MKR-USD', 'ZRX-USD', 'BAT-USD', 'ENJ-USD', 'MANA-USD',
            'SAND-USD', 'AXS-USD', 'GALA-USD', 'APE-USD', 'IMX-USD',
            'LRC-USD', 'CHZ-USD', 'FTM-USD', 'NEAR-USD', 'HBAR-USD',
            'FLOW-USD', 'ICP-USD', 'VET-USD', 'THETA-USD', 'EOS-USD',
            'XTZ-USD', 'DASH-USD', 'ZEC-USD', 'QTUM-USD', 'ONT-USD',
            'ZIL-USD', 'WAVES-USD', 'ICX-USD', 'OMG-USD', 'LSK-USD',
            'SC-USD', 'DGB-USD', 'RVN-USD', 'KMD-USD', 'STEEM-USD'
        ]
        
        positions = []
        used_symbols = set()
        
        for i in range(self.initial_position_count):
            # Select unique symbol
            symbol = random.choice([s for s in symbols if s not in used_symbols])
            used_symbols.add(symbol)
            
            # Position size distribution (realistic fragmentation)
            rand = random.random()
            if rand < 0.75:  # 75% are dust or near-dust
                size_usd = random.uniform(0.10, 0.95)
            elif rand < 0.90:  # 15% are small positions
                size_usd = random.uniform(1.00, 10.00)
            else:  # 10% are medium/large positions
                size_usd = random.uniform(10.00, 100.00)
            
            # P&L distribution (realistic mix)
            # Most positions are slightly negative (typical retail pattern)
            pnl_rand = random.random()
            if pnl_rand < 0.40:  # 40% small losses
                pnl_pct = random.uniform(-0.10, -0.01)  # -10% to -1%
            elif pnl_rand < 0.65:  # 25% small wins
                pnl_pct = random.uniform(0.01, 0.10)  # +1% to +10%
            elif pnl_rand < 0.80:  # 15% breakeven
                pnl_pct = random.uniform(-0.01, 0.01)  # -1% to +1%
            elif pnl_rand < 0.90:  # 10% larger losses
                pnl_pct = random.uniform(-0.30, -0.10)  # -30% to -10%
            else:  # 10% larger wins
                pnl_pct = random.uniform(0.10, 0.50)  # +10% to +50%
            
            # Entry time (spread over last 30 days)
            entry_time = datetime.now() - timedelta(days=random.randint(1, 30))
            
            positions.append({
                'symbol': symbol,
                'size_usd': size_usd,
                'pnl_pct': pnl_pct,
                'pnl_usd': size_usd * pnl_pct,
                'entry_time': entry_time,
                'age_hours': (datetime.now() - entry_time).total_seconds() / 3600
            })
        
        # Sort by size (smallest first) for consistent output
        positions.sort(key=lambda p: p['size_usd'])
        
        self.positions = positions
        return positions
    
    def identify_dust_positions(self) -> List[Dict]:
        """
        Identify all positions below dust threshold.
        
        Returns:
            List of dust positions that will be closed
        """
        dust = []
        
        for pos in self.positions:
            if pos['size_usd'] < self.dust_threshold_usd:
                dust.append({
                    **pos,
                    'cleanup_type': 'DUST',
                    'reason': f"Dust position (${pos['size_usd']:.2f} < ${self.dust_threshold_usd:.2f})"
                })
        
        self.dust_positions = dust
        return dust
    
    def identify_cap_excess_positions(self) -> List[Dict]:
        """
        Identify positions to close when over cap (after dust cleanup).
        
        Ranking:
        1. Smallest USD value first (minimize capital impact)
        2. Worst P&L if tied on size
        
        Returns:
            List of positions that will be closed to enforce cap
        """
        # Get positions that remain after dust cleanup
        remaining = [p for p in self.positions if p['size_usd'] >= self.dust_threshold_usd]
        
        if len(remaining) <= self.max_positions:
            self.cap_excess_positions = []
            return []
        
        # Rank by size (smallest first), then by P&L (worst first)
        ranked = sorted(remaining, key=lambda p: (p['size_usd'], p['pnl_pct']))
        
        # Determine how many to close
        excess_count = len(remaining) - self.max_positions
        
        cap_excess = []
        for pos in ranked[:excess_count]:
            cap_excess.append({
                **pos,
                'cleanup_type': 'CAP_EXCEEDED',
                'reason': f"Position cap exceeded ({len(remaining)}/{self.max_positions})"
            })
        
        self.cap_excess_positions = cap_excess
        return cap_excess
    
    def categorize_outcome(self, pnl_pct: float) -> str:
        """
        Categorize position outcome based on P&L.
        
        Args:
            pnl_pct: P&L percentage (e.g., 0.05 = +5%)
        
        Returns:
            Outcome category: WIN, LOSS, or BREAKEVEN
        """
        if pnl_pct > 0.01:  # > +1%
            return 'WIN'
        elif pnl_pct < -0.01:  # < -1%
            return 'LOSS'
        else:  # -1% to +1%
            return 'BREAKEVEN'
    
    def simulate_cleanup(self) -> Dict:
        """
        Run full cleanup simulation.
        
        Returns:
            Summary dict with all metrics
        """
        logger.info("\n" + "="*80)
        logger.info(f"🔍 SIMULATING CLEANUP FOR: {self.user_id}")
        logger.info("="*80)
        
        # Generate positions
        self.generate_realistic_positions()
        initial_count = len(self.positions)
        initial_capital = sum(p['size_usd'] for p in self.positions)
        initial_pnl = sum(p['pnl_usd'] for p in self.positions)
        
        logger.info(f"\n📊 INITIAL STATE:")
        logger.info(f"   Total Positions: {initial_count}")
        logger.info(f"   Total Capital: ${initial_capital:.2f}")
        logger.info(f"   Total P&L: ${initial_pnl:+.2f} ({(initial_pnl/initial_capital*100):+.2f}%)")
        
        # Step 1: Dust cleanup
        logger.info(f"\n🧹 STEP 1: DUST CLEANUP (threshold: ${self.dust_threshold_usd:.2f})")
        dust = self.identify_dust_positions()
        
        if dust:
            logger.info(f"   Found {len(dust)} dust positions")
            dust_capital = sum(p['size_usd'] for p in dust)
            dust_pnl = sum(p['pnl_usd'] for p in dust)
            
            logger.info(f"   Dust Capital: ${dust_capital:.2f}")
            logger.info(f"   Dust P&L: ${dust_pnl:+.2f}")
            
            # Categorize dust outcomes
            for pos in dust:
                outcome = self.categorize_outcome(pos['pnl_pct'])
                self.outcomes[outcome].append(pos)
            
            dust_wins = len([p for p in dust if self.categorize_outcome(p['pnl_pct']) == 'WIN'])
            dust_losses = len([p for p in dust if self.categorize_outcome(p['pnl_pct']) == 'LOSS'])
            dust_breakeven = len([p for p in dust if self.categorize_outcome(p['pnl_pct']) == 'BREAKEVEN'])
            
            logger.info(f"   Outcomes: {dust_wins} WINS, {dust_losses} LOSSES, {dust_breakeven} BREAKEVEN")
        else:
            logger.info("   No dust positions found")
        
        # Step 2: Cap enforcement
        logger.info(f"\n🔒 STEP 2: POSITION CAP ENFORCEMENT (max: {self.max_positions})")
        cap_excess = self.identify_cap_excess_positions()
        
        remaining_after_dust = initial_count - len(dust)
        logger.info(f"   Positions after dust cleanup: {remaining_after_dust}")
        
        if cap_excess:
            logger.info(f"   Over cap by: {len(cap_excess)} positions")
            cap_capital = sum(p['size_usd'] for p in cap_excess)
            cap_pnl = sum(p['pnl_usd'] for p in cap_excess)
            
            logger.info(f"   Cap Excess Capital: ${cap_capital:.2f}")
            logger.info(f"   Cap Excess P&L: ${cap_pnl:+.2f}")
            
            # Categorize cap excess outcomes
            for pos in cap_excess:
                outcome = self.categorize_outcome(pos['pnl_pct'])
                self.outcomes[outcome].append(pos)
            
            cap_wins = len([p for p in cap_excess if self.categorize_outcome(p['pnl_pct']) == 'WIN'])
            cap_losses = len([p for p in cap_excess if self.categorize_outcome(p['pnl_pct']) == 'LOSS'])
            cap_breakeven = len([p for p in cap_excess if self.categorize_outcome(p['pnl_pct']) == 'BREAKEVEN'])
            
            logger.info(f"   Outcomes: {cap_wins} WINS, {cap_losses} LOSSES, {cap_breakeven} BREAKEVEN")
        else:
            logger.info("   Under cap - no positions to close")
        
        # Calculate final state
        # Create set of closed position symbols for efficient lookup
        closed_symbols = set(p['symbol'] for p in dust) | set(p['symbol'] for p in cap_excess)
        closed_positions = dust + cap_excess
        self.final_positions = [p for p in self.positions if p['symbol'] not in closed_symbols]
        
        final_count = len(self.final_positions)
        final_capital = sum(p['size_usd'] for p in self.final_positions)
        final_pnl = sum(p['pnl_usd'] for p in self.final_positions)
        
        closed_capital = sum(p['size_usd'] for p in closed_positions)
        closed_pnl = sum(p['pnl_usd'] for p in closed_positions)
        
        total_wins = len(self.outcomes['WIN'])
        total_losses = len(self.outcomes['LOSS'])
        total_breakeven = len(self.outcomes['BREAKEVEN'])
        
        # Summary
        logger.info(f"\n" + "="*80)
        logger.info(f"📊 FINAL SUMMARY FOR {self.user_id}")
        logger.info("="*80)
        logger.info(f"\n🔢 POSITION COUNT:")
        logger.info(f"   Initial:   {initial_count} positions")
        logger.info(f"   Closed:    {len(closed_positions)} positions ({len(dust)} dust + {len(cap_excess)} cap excess)")
        logger.info(f"   Final:     {final_count} positions")
        logger.info(f"   Reduction: {initial_count - final_count} positions ({(1 - final_count/initial_count)*100:.1f}%)")
        
        logger.info(f"\n💰 CAPITAL ANALYSIS:")
        logger.info(f"   Initial Capital:  ${initial_capital:.2f}")
        logger.info(f"   Closed Capital:   ${closed_capital:.2f} ({(closed_capital/initial_capital*100):.1f}%)")
        logger.info(f"   Final Capital:    ${final_capital:.2f} ({(final_capital/initial_capital*100):.1f}%)")
        
        logger.info(f"\n📈 PROFIT/LOSS TRACKING:")
        logger.info(f"   Initial Total P&L:  ${initial_pnl:+.2f}")
        logger.info(f"   Closed P&L:         ${closed_pnl:+.2f}")
        logger.info(f"   Final Total P&L:    ${final_pnl:+.2f}")
        
        logger.info(f"\n🎯 CLOSED POSITION OUTCOMES:")
        logger.info(f"   WINS:      {total_wins} positions ({(total_wins/len(closed_positions)*100):.1f}%)")
        logger.info(f"   LOSSES:    {total_losses} positions ({(total_losses/len(closed_positions)*100):.1f}%)")
        logger.info(f"   BREAKEVEN: {total_breakeven} positions ({(total_breakeven/len(closed_positions)*100):.1f}%)")
        
        # Detailed position list
        logger.info(f"\n📋 POSITIONS TO BE CLOSED ({len(closed_positions)} total):")
        logger.info(f"\n   DUST POSITIONS ({len(dust)}):")
        for i, pos in enumerate(dust[:10], 1):  # Show first 10
            outcome = self.categorize_outcome(pos['pnl_pct'])
            logger.info(f"      {i}. {pos['symbol']:12s} ${pos['size_usd']:7.2f} | P&L: {pos['pnl_pct']:+7.2%} (${pos['pnl_usd']:+6.2f}) | {outcome}")
        if len(dust) > 10:
            logger.info(f"      ... ({len(dust) - 10} more dust positions)")
        
        if cap_excess:
            logger.info(f"\n   CAP EXCESS POSITIONS ({len(cap_excess)}):")
            for i, pos in enumerate(cap_excess, 1):
                outcome = self.categorize_outcome(pos['pnl_pct'])
                logger.info(f"      {i}. {pos['symbol']:12s} ${pos['size_usd']:7.2f} | P&L: {pos['pnl_pct']:+7.2%} (${pos['pnl_usd']:+6.2f}) | {outcome}")
        
        logger.info(f"\n📋 FINAL POSITIONS REMAINING ({final_count}):")
        for i, pos in enumerate(self.final_positions, 1):
            logger.info(f"      {i}. {pos['symbol']:12s} ${pos['size_usd']:7.2f} | P&L: {pos['pnl_pct']:+7.2%} (${pos['pnl_usd']:+6.2f})")
        
        return {
            'user_id': self.user_id,
            'initial_count': initial_count,
            'final_count': final_count,
            'dust_closed': len(dust),
            'cap_excess_closed': len(cap_excess),
            'total_closed': len(closed_positions),
            'initial_capital': initial_capital,
            'closed_capital': closed_capital,
            'final_capital': final_capital,
            'initial_pnl': initial_pnl,
            'closed_pnl': closed_pnl,
            'final_pnl': final_pnl,
            'outcomes': {
                'wins': total_wins,
                'losses': total_losses,
                'breakeven': total_breakeven
            }
        }


def main():
    """Run position reduction simulation for both users"""
    logger.info("\n" + "🎯" * 40)
    logger.info("USER POSITION REDUCTION SIMULATION")
    logger.info("Simulating deployment impact on user positions")
    logger.info("🎯" * 40)
    
    # Simulate user_daivon_frazier (59 positions → 8)
    daivon_sim = UserPositionSimulation(
        user_id='user_daivon_frazier',
        initial_position_count=59,
        max_positions=8,
        dust_threshold_usd=1.00
    )
    daivon_results = daivon_sim.simulate_cleanup()
    
    # Add spacing between users
    logger.info("\n\n")
    
    # Simulate user_tania_gilbert (54 positions → 8)
    tania_sim = UserPositionSimulation(
        user_id='user_tania_gilbert',
        initial_position_count=54,
        max_positions=8,
        dust_threshold_usd=1.00
    )
    tania_results = tania_sim.simulate_cleanup()
    
    # Overall summary
    logger.info("\n\n" + "="*80)
    logger.info("🎯 COMBINED DEPLOYMENT IMPACT")
    logger.info("="*80)
    
    total_initial = daivon_results['initial_count'] + tania_results['initial_count']
    total_final = daivon_results['final_count'] + tania_results['final_count']
    total_closed = daivon_results['total_closed'] + tania_results['total_closed']
    
    total_wins = daivon_results['outcomes']['wins'] + tania_results['outcomes']['wins']
    total_losses = daivon_results['outcomes']['losses'] + tania_results['outcomes']['losses']
    total_breakeven = daivon_results['outcomes']['breakeven'] + tania_results['outcomes']['breakeven']
    
    combined_initial_capital = daivon_results['initial_capital'] + tania_results['initial_capital']
    combined_closed_capital = daivon_results['closed_capital'] + tania_results['closed_capital']
    combined_final_capital = daivon_results['final_capital'] + tania_results['final_capital']
    
    combined_initial_pnl = daivon_results['initial_pnl'] + tania_results['initial_pnl']
    combined_closed_pnl = daivon_results['closed_pnl'] + tania_results['closed_pnl']
    combined_final_pnl = daivon_results['final_pnl'] + tania_results['final_pnl']
    
    logger.info(f"\n📊 BOTH USERS COMBINED:")
    logger.info(f"   Initial Positions:  {total_initial}")
    logger.info(f"   Positions Closed:   {total_closed}")
    logger.info(f"   Final Positions:    {total_final}")
    logger.info(f"   Reduction:          {total_initial - total_final} ({(1 - total_final/total_initial)*100:.1f}%)")
    
    logger.info(f"\n💰 COMBINED CAPITAL:")
    logger.info(f"   Initial Capital:  ${combined_initial_capital:.2f}")
    logger.info(f"   Closed Capital:   ${combined_closed_capital:.2f} ({(combined_closed_capital/combined_initial_capital*100):.1f}%)")
    logger.info(f"   Final Capital:    ${combined_final_capital:.2f} ({(combined_final_capital/combined_initial_capital*100):.1f}%)")
    
    logger.info(f"\n📈 COMBINED P&L:")
    logger.info(f"   Initial Total P&L:  ${combined_initial_pnl:+.2f}")
    logger.info(f"   Closed P&L:         ${combined_closed_pnl:+.2f}")
    logger.info(f"   Final Total P&L:    ${combined_final_pnl:+.2f}")
    
    logger.info(f"\n🎯 COMBINED OUTCOMES:")
    logger.info(f"   WINS:      {total_wins} positions ({(total_wins/total_closed*100):.1f}%)")
    logger.info(f"   LOSSES:    {total_losses} positions ({(total_losses/total_closed*100):.1f}%)")
    logger.info(f"   BREAKEVEN: {total_breakeven} positions ({(total_breakeven/total_closed*100):.1f}%)")
    
    logger.info("\n" + "="*80)
    logger.info("✅ SIMULATION COMPLETE")
    logger.info("="*80)
    logger.info("\nThis simulation shows exactly what will happen during deployment:")
    logger.info("1. Dust positions (< $1 USD) are identified and closed")
    logger.info("2. Remaining positions over the 8-position cap are closed (smallest first)")
    logger.info("3. Each user ends up with exactly 8 positions")
    logger.info("4. All closed positions have their profit/loss realized and tracked")
    logger.info("\n")


if __name__ == '__main__':
    # Set random seed for reproducible results in demo
    random.seed(42)
    main()
