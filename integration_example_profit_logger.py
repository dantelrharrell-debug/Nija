#!/usr/bin/env python3
"""
Integration Example: Using Profit Confirmation Logger with Execution Engine

This shows how to:
1. Check if profit is "proven" before taking profit
2. Generate simple 24-72h reports
3. Track profit confirmations vs givebacks
"""

import sys
import os
import logging
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from profit_confirmation_logger import ProfitConfirmationLogger

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)


def example_position_management():
    """
    Example: Using profit confirmation logger for position management
    """
    
    # Initialize the logger
    profit_logger = ProfitConfirmationLogger(data_dir="./data")
    
    # Simulate an open position
    symbol = 'BTC-USD'
    entry_price = 42000.0
    entry_time = datetime.now() - timedelta(minutes=10)  # Position opened 10 minutes ago
    position_size_usd = 100.0
    current_price = 42800.0
    broker_fee_pct = 0.014  # 1.4% for Coinbase
    side = 'long'
    
    logger.info("\n" + "="*60)
    logger.info("EXAMPLE: Position Management with Profit Confirmation")
    logger.info("="*60)
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Entry: ${entry_price:.2f}")
    logger.info(f"Current: ${current_price:.2f}")
    logger.info(f"Position opened: {entry_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Hold time: {(datetime.now() - entry_time).total_seconds()/60:.1f} minutes")
    
    # Check if profit is "proven"
    result = profit_logger.check_profit_proven(
        symbol=symbol,
        entry_price=entry_price,
        current_price=current_price,
        entry_time=entry_time,
        position_size_usd=position_size_usd,
        broker_fee_pct=broker_fee_pct,
        side=side
    )
    
    logger.info("\n" + "-"*60)
    logger.info("PROFIT PROVEN CHECK:")
    logger.info("-"*60)
    logger.info(f"Gross Profit: {result['gross_profit_pct']*100:+.2f}%")
    logger.info(f"NET Profit (after fees): {result['net_profit_pct']*100:+.2f}%")
    logger.info(f"NET Profit USD: ${result['net_profit_usd']:+.2f}")
    logger.info(f"Hold time: {result['hold_time_seconds']:.0f}s")
    logger.info("")
    logger.info("Criteria met:")
    logger.info(f"  ✓ Profit threshold (>0.5%): {result['criteria_met']['profit_threshold']}")
    logger.info(f"  ✓ Hold time (>120s): {result['criteria_met']['hold_time']}")
    logger.info(f"  ✓ No giveback: {result['criteria_met']['no_giveback']}")
    logger.info("")
    logger.info(f"PROFIT PROVEN: {'✅ YES' if result['proven'] else '❌ NO'}")
    logger.info(f"Recommended action: {result['action']}")
    
    # If profit is proven, take it!
    if result['proven']:
        logger.info("\n" + "="*60)
        logger.info("✅ TAKING PROFIT - All criteria met!")
        logger.info("="*60)
        
        profit_logger.log_profit_confirmation(
            symbol=symbol,
            entry_price=entry_price,
            exit_price=current_price,
            position_size_usd=position_size_usd,
            net_profit_pct=result['net_profit_pct'],
            net_profit_usd=result['net_profit_usd'],
            hold_time_seconds=result['hold_time_seconds'],
            exit_type='PROFIT_CONFIRMED',
            fees_paid_usd=position_size_usd * broker_fee_pct,
            risk_amount_usd=position_size_usd * 0.008  # Risked 0.8%
        )
    else:
        logger.info("\n" + "="*60)
        logger.info(f"⏳ HOLDING POSITION - {result['action']}")
        logger.info("="*60)


def example_profit_report():
    """
    Example: Generate simple profit reports
    """
    
    # Initialize the logger
    profit_logger = ProfitConfirmationLogger(data_dir="./data")
    
    logger.info("\n\n" + "="*60)
    logger.info("EXAMPLE: Simple Profit Reports")
    logger.info("="*60 + "\n")
    
    # Simulate account equity
    starting_equity_24h = 1000.00
    starting_equity_48h = 995.00
    current_equity = 1001.06
    
    # Generate 24-hour report
    logger.info("24-HOUR REPORT:")
    logger.info("-"*60)
    profit_logger.print_simple_report(
        starting_equity=starting_equity_24h,
        ending_equity=current_equity,
        hours=24
    )
    
    # Generate 48-hour report
    logger.info("\n48-HOUR REPORT:")
    logger.info("-"*60)
    profit_logger.print_simple_report(
        starting_equity=starting_equity_48h,
        ending_equity=current_equity,
        hours=48
    )


def example_daily_summary():
    """
    Example: Daily profit confirmation summary
    """
    
    # Initialize the logger
    profit_logger = ProfitConfirmationLogger(data_dir="./data")
    
    logger.info("\n\n" + "="*60)
    logger.info("EXAMPLE: Daily Summary")
    logger.info("="*60 + "\n")
    
    profit_logger.log_daily_summary()


def example_position_cleanup():
    """
    Example: Clean up stale position tracking
    """
    
    # Initialize the logger
    profit_logger = ProfitConfirmationLogger(data_dir="./data")
    
    logger.info("\n\n" + "="*60)
    logger.info("EXAMPLE: Position Cleanup")
    logger.info("="*60 + "\n")
    
    # Simulate active positions
    active_positions = ['BTC-USD', 'ETH-USD']
    
    # Clean up stale tracking
    cleaned = profit_logger.cleanup_stale_tracking(active_positions)
    
    if cleaned > 0:
        logger.info(f"✅ Cleaned up {cleaned} stale tracking entries")
    else:
        logger.info("✅ No stale tracking entries found")


if __name__ == '__main__':
    logger.info("\n" + "#"*60)
    logger.info("# Profit Confirmation Logger - Integration Examples")
    logger.info("#"*60)
    
    # Run examples
    example_position_management()
    example_profit_report()
    example_daily_summary()
    example_position_cleanup()
    
    logger.info("\n" + "#"*60)
    logger.info("# Examples Complete!")
    logger.info("#"*60 + "\n")
