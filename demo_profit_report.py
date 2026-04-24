#!/usr/bin/env python3
"""
Demo script for Profit Confirmation Logger

Shows how to use the simple report feature.
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

def demo_profit_report():
    """Demonstrate the simple profit report"""
    
    # Initialize logger
    logger = ProfitConfirmationLogger(data_dir="./data")
    
    # Simulate some trades
    print("\n" + "="*60)
    print("Simulating 5 trades over last 24 hours...")
    print("="*60 + "\n")
    
    # Trade 1: Winner
    logger.log_profit_confirmation(
        symbol='BTC-USD',
        entry_price=42000.0,
        exit_price=42800.0,
        position_size_usd=100.0,
        net_profit_pct=0.0076,  # 0.76% NET profit
        net_profit_usd=0.76,
        hold_time_seconds=1800,  # 30 minutes
        exit_type='PROFIT_CONFIRMED',
        fees_paid_usd=1.24,
        risk_amount_usd=0.80  # Risked $0.80
    )
    
    # Trade 2: Winner
    logger.log_profit_confirmation(
        symbol='ETH-USD',
        entry_price=2200.0,
        exit_price=2265.0,
        position_size_usd=100.0,
        net_profit_pct=0.0156,  # 1.56% NET profit
        net_profit_usd=1.56,
        hold_time_seconds=2400,  # 40 minutes
        exit_type='PROFIT_CONFIRMED',
        fees_paid_usd=1.44,
        risk_amount_usd=0.80
    )
    
    # Trade 3: Small winner
    logger.log_profit_confirmation(
        symbol='SOL-USD',
        entry_price=95.0,
        exit_price=96.5,
        position_size_usd=50.0,
        net_profit_pct=0.0044,  # 0.44% NET profit
        net_profit_usd=0.22,
        hold_time_seconds=900,  # 15 minutes
        exit_type='PROFIT_CONFIRMED',
        fees_paid_usd=0.78,
        risk_amount_usd=0.40
    )
    
    # Trade 4: Loser (stopped out)
    logger.log_profit_confirmation(
        symbol='AVAX-USD',
        entry_price=32.0,
        exit_price=31.6,
        position_size_usd=75.0,
        net_profit_pct=-0.0165,  # -1.65% NET loss
        net_profit_usd=-1.24,
        hold_time_seconds=600,  # 10 minutes
        exit_type='STOP_LOSS',
        fees_paid_usd=0.51,
        risk_amount_usd=0.75
    )
    
    # Trade 5: Giveback
    logger.log_profit_confirmation(
        symbol='ADA-USD',
        entry_price=0.50,
        exit_price=0.505,
        position_size_usd=60.0,
        net_profit_pct=-0.0040,  # -0.40% NET (gave back profit)
        net_profit_usd=-0.24,
        hold_time_seconds=1200,  # 20 minutes
        exit_type='PROFIT_GIVEBACK',
        fees_paid_usd=0.64,
        risk_amount_usd=0.60
    )
    
    print("\n" + "="*60)
    print("Generating 24-hour profit report...")
    print("="*60 + "\n")
    
    # Generate and print report
    starting_equity = 1000.00
    ending_equity = 1001.06  # Net profit of $1.06
    
    logger.print_simple_report(
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        hours=24
    )
    
    print("\n" + "="*60)
    print("Generating 48-hour profit report...")
    print("="*60 + "\n")
    
    logger.print_simple_report(
        starting_equity=995.00,
        ending_equity=1001.06,
        hours=48
    )
    
    # Show summary statistics
    print("\n" + "="*60)
    print("Overall statistics:")
    print("="*60)
    summary = logger.get_confirmation_summary()
    print(f"Total confirmations: {summary['total_confirmations']}")
    print(f"Total givebacks: {summary['total_givebacks']}")
    print(f"Confirmation rate: {summary['confirmation_rate']:.1f}%")
    print(f"Total profit taken: ${summary['total_profit_taken_usd']:.2f}")
    print(f"Total profit given back: ${summary['total_profit_given_back_usd']:.2f}")
    print(f"NET profit: ${summary['net_profit_usd']:.2f}")
    print("="*60 + "\n")


if __name__ == '__main__':
    demo_profit_report()
