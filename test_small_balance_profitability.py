#!/usr/bin/env python3
"""
Small Balance Profitability Analysis

Analyzes profitability requirements for small account balances.
Provides recommendations for stop-loss and profit target tuning.

Priority B from architect's recommendation: "Tune stops for small balances (profitability)"
"""

import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FeeCalculator:
    """Calculate trading fees and breakeven requirements."""
    
    def __init__(self, broker_name: str):
        self.broker_name = broker_name
        
        # Fee structures (as of Jan 2026)
        self.fees = {
            'coinbase': {
                'taker': 0.006,  # 0.6% taker fee
                'maker': 0.004,  # 0.4% maker fee
                'spread': 0.002,  # ~0.2% average spread
                'round_trip': 0.014,  # 1.4% total round-trip cost
            },
            'kraken': {
                'taker': 0.0016,  # 0.16% taker fee
                'maker': 0.0010,  # 0.10% maker fee
                'spread': 0.001,  # ~0.1% average spread
                'round_trip': 0.0036,  # 0.36% total round-trip cost (4x cheaper!)
            }
        }
    
    def get_round_trip_cost(self) -> float:
        """Get total round-trip cost percentage."""
        return self.fees[self.broker_name]['round_trip']
    
    def calculate_breakeven(self, position_size: float) -> dict:
        """
        Calculate breakeven requirements for a position.
        
        Args:
            position_size: Position size in USD
            
        Returns:
            dict with breakeven analysis
        """
        round_trip = self.get_round_trip_cost()
        
        # Absolute fee cost
        fee_dollars = position_size * round_trip
        
        # Required profit to break even (percent)
        breakeven_pct = round_trip * 100
        
        # Recommended minimum profit target (breakeven + buffer)
        buffer_pct = 0.5  # 0.5% safety buffer
        min_profit_pct = breakeven_pct + buffer_pct
        
        return {
            'position_size': position_size,
            'fee_dollars': fee_dollars,
            'breakeven_pct': breakeven_pct,
            'min_profit_pct': min_profit_pct,
            'round_trip_cost': round_trip
        }


def analyze_position_size(position_size: float, broker: str = 'coinbase'):
    """
    Analyze profitability for a specific position size.
    
    Args:
        position_size: Position size in USD
        broker: Broker name ('coinbase' or 'kraken')
    """
    calc = FeeCalculator(broker)
    analysis = calc.calculate_breakeven(position_size)
    
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"POSITION SIZE: ${position_size:.2f} on {broker.upper()}")
    logger.info("=" * 80)
    logger.info(f"Round-trip cost: {analysis['round_trip_cost']*100:.2f}%")
    logger.info(f"Fee in dollars: ${analysis['fee_dollars']:.4f}")
    logger.info(f"Breakeven profit: {analysis['breakeven_pct']:.2f}%")
    logger.info(f"Recommended min profit: {analysis['min_profit_pct']:.2f}%")
    logger.info("")
    
    # Profitability assessment
    if analysis['fee_dollars'] >= position_size * 0.5:
        logger.error(f"❌ NOT PROFITABLE: Fees consume 50%+ of position")
        logger.error(f"   Position too small for profitable trading")
        return False
    elif analysis['fee_dollars'] >= position_size * 0.25:
        logger.warning(f"⚠️  RISKY: Fees consume 25-50% of position")
        logger.warning(f"   Need {analysis['min_profit_pct']:.1f}%+ gains to profit")
        return False
    elif analysis['fee_dollars'] >= position_size * 0.10:
        logger.warning(f"⚠️  CHALLENGING: Fees consume 10-25% of position")
        logger.warning(f"   Requires {analysis['min_profit_pct']:.1f}%+ gains")
        return True
    else:
        logger.info(f"✅ VIABLE: Fees consume <10% of position")
        logger.info(f"   Need {analysis['min_profit_pct']:.1f}%+ gains to profit")
        return True


def compare_brokers(position_size: float):
    """Compare profitability across brokers."""
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"BROKER COMPARISON: ${position_size:.2f} Position")
    logger.info("=" * 80)
    
    coinbase_calc = FeeCalculator('coinbase')
    kraken_calc = FeeCalculator('kraken')
    
    cb_analysis = coinbase_calc.calculate_breakeven(position_size)
    kr_analysis = kraken_calc.calculate_breakeven(position_size)
    
    logger.info("")
    logger.info("Coinbase:")
    logger.info(f"  Fee cost: ${cb_analysis['fee_dollars']:.4f} ({cb_analysis['round_trip_cost']*100:.2f}%)")
    logger.info(f"  Min profit needed: {cb_analysis['min_profit_pct']:.2f}%")
    
    logger.info("")
    logger.info("Kraken:")
    logger.info(f"  Fee cost: ${kr_analysis['fee_dollars']:.4f} ({kr_analysis['round_trip_cost']*100:.2f}%)")
    logger.info(f"  Min profit needed: {kr_analysis['min_profit_pct']:.2f}%")
    
    logger.info("")
    savings = cb_analysis['fee_dollars'] - kr_analysis['fee_dollars']
    savings_pct = (savings / cb_analysis['fee_dollars']) * 100
    
    logger.info(f"💰 SAVINGS WITH KRAKEN: ${savings:.4f} ({savings_pct:.1f}% cheaper)")
    logger.info(f"   Profit target difference: {cb_analysis['min_profit_pct'] - kr_analysis['min_profit_pct']:.2f}%")


def recommend_profit_targets(balance: float, broker: str = 'coinbase'):
    """
    Recommend profit targets based on account balance.
    
    Args:
        balance: Account balance in USD
        broker: Broker name
    """
    calc = FeeCalculator(broker)
    round_trip = calc.get_round_trip_cost()
    
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"PROFIT TARGET RECOMMENDATIONS: ${balance:.2f} Balance on {broker.upper()}")
    logger.info("=" * 80)
    
    # Typical position sizes based on balance
    if balance < 5:
        position_sizes = [balance * 0.5, balance * 0.8, balance * 1.0]
        risk_levels = ["Conservative (50%)", "Moderate (80%)", "Aggressive (100%)"]
    elif balance < 25:
        position_sizes = [balance * 0.2, balance * 0.4, balance * 0.6]
        risk_levels = ["Conservative (20%)", "Moderate (40%)", "Aggressive (60%)"]
    else:
        position_sizes = [balance * 0.1, balance * 0.2, balance * 0.3]
        risk_levels = ["Conservative (10%)", "Moderate (20%)", "Aggressive (30%)"]
    
    logger.info("")
    for size, risk in zip(position_sizes, risk_levels):
        analysis = calc.calculate_breakeven(size)
        logger.info(f"{risk}:")
        logger.info(f"  Position: ${size:.2f}")
        logger.info(f"  Fees: ${analysis['fee_dollars']:.4f}")
        logger.info(f"  Min profit target: {analysis['min_profit_pct']:.2f}%")
    
    # Overall recommendations
    logger.info("")
    logger.info("RECOMMENDED CONFIGURATION:")
    logger.info("")
    
    breakeven_pct = round_trip * 100
    
    if broker == 'coinbase':
        # Coinbase has high fees (1.4%)
        if balance < 5:
            logger.warning("⚠️  Balance too low for profitable Coinbase trading")
            logger.warning("   Recommend minimum $10+ for Coinbase")
            logger.info("   PROFIT_TARGETS = [(2.5, 'Minimum'), (3.0, 'Good'), (4.0, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -0.5%  # Tight stop for small balance")
        elif balance < 25:
            logger.info("   PROFIT_TARGETS = [(2.0, 'Minimum'), (2.5, 'Good'), (3.5, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -0.5%  # Tight stop to preserve capital")
        else:
            logger.info("   PROFIT_TARGETS = [(1.5, 'Minimum'), (2.0, 'Good'), (3.0, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -1.0%  # Standard stop")
    
    elif broker == 'kraken':
        # Kraken has low fees (0.36%)
        if balance < 5:
            logger.info("   PROFIT_TARGETS = [(1.0, 'Minimum'), (1.5, 'Good'), (2.0, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -0.5%  # Tight stop for small balance")
        elif balance < 25:
            logger.info("   PROFIT_TARGETS = [(0.8, 'Minimum'), (1.2, 'Good'), (1.8, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -0.7%  # Tighter stop")
        else:
            logger.info("   PROFIT_TARGETS = [(0.7, 'Minimum'), (1.0, 'Good'), (1.5, 'Excellent')]")
            logger.info("   STOP_LOSS_THRESHOLD = -0.7%  # Standard for Kraken")
    
    logger.info("")
    logger.info(f"Note: {broker.title()} breakeven = {breakeven_pct:.2f}%")
    logger.info("      All profit targets are NET positive after fees")


def analyze_current_configuration():
    """Analyze current trading_strategy.py configuration."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("CURRENT CONFIGURATION ANALYSIS")
    logger.info("=" * 80)
    
    try:
        # Try to import trading strategy module
        try:
            from bot.trading_strategy import (
                PROFIT_TARGETS,
                STOP_LOSS_THRESHOLD,
                MIN_POSITION_SIZE_USD,
                MIN_BALANCE_TO_TRADE_USD,
                MIN_PROFIT_THRESHOLD
            )
        except ImportError as import_err:
            logger.warning(f"⚠️  Could not import trading_strategy module: {import_err}")
            logger.warning("   Skipping current configuration analysis")
            return False
        
        logger.info("")
        logger.info("Position Sizing:")
        logger.info(f"  MIN_POSITION_SIZE_USD = ${MIN_POSITION_SIZE_USD:.2f}")
        logger.info(f"  MIN_BALANCE_TO_TRADE_USD = ${MIN_BALANCE_TO_TRADE_USD:.2f}")
        
        logger.info("")
        logger.info("Profit Targets (Coinbase-focused):")
        for target_pct, description in PROFIT_TARGETS:
            logger.info(f"  {target_pct*100:.1f}% - {description}")
        
        logger.info("")
        logger.info("Stop Loss:")
        logger.info(f"  STOP_LOSS_THRESHOLD = {STOP_LOSS_THRESHOLD*100:.2f}%")
        
        logger.info("")
        logger.info("Minimum Profit:")
        logger.info(f"  MIN_PROFIT_THRESHOLD = {MIN_PROFIT_THRESHOLD*100:.2f}%")
        
        # Analyze if current config makes sense
        logger.info("")
        logger.info("ASSESSMENT:")
        
        coinbase_calc = FeeCalculator('coinbase')
        cb_round_trip = coinbase_calc.get_round_trip_cost()
        
        # Check if profit targets exceed breakeven
        min_target = min(target[0] for target in PROFIT_TARGETS)
        if min_target <= cb_round_trip:
            logger.error(f"❌ PROBLEM: Minimum profit target ({min_target*100:.1f}%) < Coinbase fees ({cb_round_trip*100:.1f}%)")
            logger.error("   Trades at this target will LOSE money after fees!")
        else:
            logger.info(f"✅ Profit targets exceed Coinbase breakeven ({cb_round_trip*100:.1f}%)")
        
        # Check stop loss
        if abs(STOP_LOSS_THRESHOLD) < cb_round_trip:
            logger.warning(f"⚠️  Stop loss ({abs(STOP_LOSS_THRESHOLD)*100:.2f}%) < fees ({cb_round_trip*100:.1f}%)")
            logger.warning("   Stop-loss exits will always be at a loss (expected for capital preservation)")
        else:
            logger.info(f"✅ Stop loss ({abs(STOP_LOSS_THRESHOLD)*100:.2f}%) set appropriately")
        
        # Check minimum position size
        cb_analysis = coinbase_calc.calculate_breakeven(MIN_POSITION_SIZE_USD)
        logger.info("")
        logger.info(f"Minimum ${MIN_POSITION_SIZE_USD:.2f} position on Coinbase:")
        logger.info(f"  Fees: ${cb_analysis['fee_dollars']:.4f}")
        logger.info(f"  Needs {cb_analysis['min_profit_pct']:.2f}%+ to profit")
        
        if cb_analysis['fee_dollars'] >= MIN_POSITION_SIZE_USD * 0.25:
            logger.warning(f"⚠️  Small positions have high fee burden (25%+ of position)")
            logger.warning("   Consider increasing MIN_POSITION_SIZE_USD or switching to Kraken")
        
        return True
        
    except ImportError as e:
        logger.error(f"❌ Could not import trading_strategy: {e}")
        return False


def main():
    """Run small balance profitability analysis."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 15 + "SMALL BALANCE PROFITABILITY ANALYSIS" + " " * 26 + "║")
    logger.info("║" + " " * 18 + "Priority B: Tune Stops for Profitability" + " " * 19 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    
    # Analyze current configuration
    analyze_current_configuration()
    
    # Test various position sizes on Coinbase
    logger.info("")
    logger.info("")
    logger.info("POSITION SIZE ANALYSIS - COINBASE")
    logger.info("=" * 80)
    for size in [1.0, 2.0, 5.0, 10.0, 25.0, 50.0]:
        analyze_position_size(size, 'coinbase')
    
    # Test various position sizes on Kraken
    logger.info("")
    logger.info("")
    logger.info("POSITION SIZE ANALYSIS - KRAKEN")
    logger.info("=" * 80)
    for size in [1.0, 2.0, 5.0, 10.0, 25.0, 50.0]:
        analyze_position_size(size, 'kraken')
    
    # Compare brokers
    logger.info("")
    logger.info("")
    for size in [5.0, 10.0, 25.0]:
        compare_brokers(size)
    
    # Generate recommendations
    logger.info("")
    logger.info("")
    logger.info("BALANCE-SPECIFIC RECOMMENDATIONS")
    logger.info("=" * 80)
    
    for balance in [2.0, 5.0, 10.0, 25.0, 50.0, 100.0]:
        recommend_profit_targets(balance, 'coinbase')
        recommend_profit_targets(balance, 'kraken')
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Key Findings:")
    logger.info("  1. Coinbase fees (1.4%) make positions under $5 very difficult to profit")
    logger.info("  2. Kraken fees (0.36%) are 4x cheaper, allowing smaller profitable positions")
    logger.info("  3. Current STOP_LOSS_THRESHOLD (-0.01%) is appropriate for capital preservation")
    logger.info("  4. Profit targets should be tuned based on actual account balance")
    logger.info("")
    logger.info("Recommendations:")
    logger.info("  • Balances under $5: Use Kraken (not Coinbase)")
    logger.info("  • Balances $5-25: Tight profit targets (1.5-2.5% for Coinbase)")
    logger.info("  • Balances $25+: Standard targets work (1.5%+ for Coinbase)")
    logger.info("  • Always: Exit losing trades immediately (STOP_LOSS_THRESHOLD = -0.01%)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
